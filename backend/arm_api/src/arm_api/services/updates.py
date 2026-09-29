"""Пакетное обновление учебного контента и настроек (ТЗ: пакетное обновление, ручной режим).

Пакет - zip-архив:

    manifest.json        {"format": 1, "version": "2026.10.1", "title": "...",
                          "contents": {"scenarios": "scenarios.json",
                                       "settings": "settings.xml",
                                       "materials": [{"file": "materials/памятка.pdf",
                                                      "title": "Памятка", "category_code": "G01.0001"}]}}
    scenarios.json       {"scenarios": [...]}   - тот же формат, что у POST /scenarios/import
    settings.xml         <settings version="1">...</settings> - как у /system/settings/export.xml
    materials/...        файлы материалов (pdf, docx, txt, csv, json, xml, mp3, wav)

Обновление кода и образов выполняется пересборкой docker (см. README), этот механизм
обновляет только данные. Читается архив осторожно: без выхода за пределы каталога,
с ограничением числа файлов и распакованного размера (защита от zip-бомбы).
"""

import io
import json
import posixpath
import re
import zipfile

MANIFEST_FORMAT = 1
MAX_ENTRIES = 1000
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MATERIAL_EXTENSIONS = {"pdf", "docx", "json", "csv", "xml", "mp3", "wav", "txt"}
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")


class PackageError(ValueError):
    """Пакет непригоден; args[0] - список понятных причин."""

    def __init__(self, problems):
        self.problems = problems if isinstance(problems, list) else [problems]
        super().__init__("; ".join(self.problems))


def safe_name(name):
    """Нормализованный путь внутри архива или None, если он небезопасен."""
    if not name or name.startswith(("/", "\\")) or "\\" in name or "\x00" in name:
        return None
    clean = posixpath.normpath(name)
    if clean.startswith("..") or clean == "." or "/../" in f"/{clean}/":
        return None
    return clean


def _problems_for_file_sections(contents):
    problems = []
    for key in contents:
        if key not in {"scenarios", "settings", "materials"}:
            problems.append(f"contents.{key}: неизвестный раздел")
    for key in ("scenarios", "settings"):
        if key in contents and (
            not isinstance(contents[key], str) or safe_name(contents[key]) is None
        ):
            problems.append(f"contents.{key}: ожидается путь к файлу внутри пакета")
    return problems


def _problems_for_material(index, entry):
    label = f"contents.materials[{index}]"
    if not isinstance(entry, dict):
        return [f"{label}: ожидается объект"]
    problems = []
    file = entry.get("file")
    if not isinstance(file, str) or safe_name(file) is None:
        problems.append(f"{label}.file: небезопасный или пустой путь")
    elif file.rsplit(".", 1)[-1].lower() not in MATERIAL_EXTENSIONS:
        problems.append(f"{label}.file: неподдерживаемый тип файла")
    if not isinstance(entry.get("title"), str) or not entry["title"].strip():
        problems.append(f"{label}.title: нужно название")
    return problems


def validate_manifest(manifest):
    """Список нарушений структуры manifest.json (пустой - манифест корректен)."""
    if not isinstance(manifest, dict):
        return ["manifest.json должен быть JSON-объектом"]
    problems = []
    if manifest.get("format") != MANIFEST_FORMAT:
        problems.append(f"format должен быть {MANIFEST_FORMAT}")
    version = manifest.get("version")
    if not isinstance(version, str) or not _VERSION.match(version):
        problems.append("version: строка из букв, цифр и . _ + - (до 64 символов)")
    title = manifest.get("title")
    if title is not None and (not isinstance(title, str) or len(title) > 255):
        problems.append("title: строка до 255 символов")
    contents = manifest.get("contents")
    if not isinstance(contents, dict) or not contents:
        problems.append(
            "contents: нужен хотя бы один раздел (scenarios, materials, settings)"
        )
        return problems
    problems += _problems_for_file_sections(contents)
    materials = contents.get("materials", [])
    if not isinstance(materials, list):
        problems.append("contents.materials: ожидается список")
    else:
        for index, entry in enumerate(materials):
            problems += _problems_for_material(index, entry)
    return problems


def _read_entries(archive):
    infos = [i for i in archive.infolist() if not i.is_dir()]
    if len(infos) > MAX_ENTRIES:
        raise PackageError(f"в пакете больше {MAX_ENTRIES} файлов")
    if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES or any(
        i.file_size > MAX_FILE_BYTES for i in infos
    ):
        raise PackageError("слишком большой распакованный размер пакета")
    files = {}
    for info in infos:
        name = safe_name(info.filename)
        if name is None:
            raise PackageError(f"небезопасный путь в архиве: {info.filename!r}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise PackageError(f"символические ссылки запрещены: {info.filename!r}")
        files[name] = archive.read(info)
    return files


def _read_manifest(files):
    if "manifest.json" not in files:
        raise PackageError("в пакете нет manifest.json")
    try:
        manifest = json.loads(files["manifest.json"].decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise PackageError("manifest.json не является корректным JSON")
    problems = validate_manifest(manifest)
    if problems:
        raise PackageError(problems)
    return manifest


def read_package(data):
    """Разбирает zip. Возвращает {'manifest', 'files': {путь: bytes}} или бросает PackageError."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PackageError("файл не является zip-архивом")
    with archive:
        files = _read_entries(archive)
    manifest = _read_manifest(files)
    contents = manifest["contents"]
    referenced = [contents[k] for k in ("scenarios", "settings") if k in contents]
    referenced += [m["file"] for m in contents.get("materials", [])]
    missing = [name for name in referenced if safe_name(name) not in files]
    if missing:
        raise PackageError([f"в пакете нет файла {name}" for name in missing])
    return {"manifest": manifest, "files": files}
