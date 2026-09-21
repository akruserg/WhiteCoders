"""База знаний: текст загруженных материалов как контекст для ИИ.

Обучение модели здесь не выполняется (модель работает локально и не дообучается).
Материал разбирается на текст, режется на фрагменты, и при генерации или
коррекции сценария в запрос к модели подставляются самые подходящие фрагменты
(поиск по основам слов с весами IDF). Так «Памятка для ДДС» и другие документы
преподавателя влияют на сценарии без внешних сервисов.

Поддерживаются pdf, docx, txt, csv, json, xml. Аудио (mp3, wav) не расшифровывается:
для него индексация возвращает 0 фрагментов.
"""

import csv
import io
import json
import logging
import math
import re
import zipfile

from defusedxml import ElementTree as SafeET
from sqlalchemy import or_, select

from ..core.extensions import db
from ..models import Material, MaterialChunk

logger = logging.getLogger(__name__)

MAX_CHARS = 3_000_000  # больше этого документ не разбираем
CHUNK_CHARS = 900
MAX_PDF_PAGES = 800
MAX_CANDIDATES = 6000

_WORD = re.compile(r"[а-яёa-z0-9]{3,}", re.IGNORECASE)
_STOP = {
    "что", "как", "это", "или", "для", "при", "над", "под", "его", "ее", "она",
    "они", "оно", "был", "была", "были", "быть", "есть", "все", "всё", "так",
    "если", "чтобы", "также", "который", "которая", "которые", "только", "уже",
}  # fmt: skip


def stems(text):
    """Основы слов: нижний регистр, е вместо ё, окончания отсекаются по первым 5 буквам."""
    result = []
    for word in _WORD.findall((text or "").lower().replace("ё", "е")):
        if word in _STOP:
            continue
        result.append(word[:5] if len(word) > 5 else word)
    return result


# ---------------------------------------------------------------- извлечение текста


def _pdf_text(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf не установлен: PDF не индексируется")
        return ""
    reader = PdfReader(path)
    parts = []
    for page in reader.pages[:MAX_PDF_PAGES]:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _docx_text(path):
    """DOCX - это zip с XML: берем текст абзацев без сторонних библиотек."""
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("word/document.xml")
    root = SafeET.fromstring(raw)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(ns + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(ns + "t"))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _flatten_json(value):
    if isinstance(value, dict):
        return "\n".join(_flatten_json(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten_json(v) for v in value)
    return "" if value is None else str(value)


def _read_text(path):
    with open(path, "rb") as handle:
        raw = handle.read(MAX_CHARS * 4)
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def extract_text(path, kind):
    """Текст материала по расширению файла (kind: pdf, docx, txt, csv, json, xml)."""
    if kind == "pdf":
        text = _pdf_text(path)
    elif kind == "docx":
        text = _docx_text(path)
    elif kind == "json":
        text = _flatten_json(json.loads(_read_text(path)))
    elif kind == "xml":
        root = SafeET.fromstring(_read_text(path).encode("utf-8"))
        text = "\n".join(t.strip() for t in root.itertext() if t and t.strip())
    elif kind == "csv":
        rows = csv.reader(io.StringIO(_read_text(path)))
        text = "\n".join(" ".join(cell for cell in row if cell) for row in rows)
    elif kind == "txt":
        text = _read_text(path)
    else:
        return ""  # аудио и прочее
    return text[:MAX_CHARS]


def split_chunks(text, size=CHUNK_CHARS):
    """Фрагменты по абзацам, не длиннее size символов (длинный абзац режется по предложениям)."""
    chunks, current = [], ""
    for paragraph in re.split(r"\n\s*\n|\n", text):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue
        pieces = [paragraph]
        if len(paragraph) > size:
            pieces = re.split(r"(?<=[.!?])\s+", paragraph)
        for piece in pieces:
            while len(piece) > size:  # предложение без точек
                chunks.append(piece[:size])
                piece = piece[size:]
            if current and len(current) + 1 + len(piece) > size:
                chunks.append(current)
                current = piece
            else:
                current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------- индексация и поиск


def kind_of(material):
    return (material.file_path or "").rsplit(".", 1)[-1].lower()


def index_material(material):
    """Разбирает файл материала и пересоздает его фрагменты. Возвращает их число."""
    try:
        text = extract_text(material.file_path, kind_of(material))
    except Exception as exc:  # битый файл не должен ронять запрос
        logger.warning("не удалось разобрать материал %s: %s", material.id, exc)
        text = ""
    db.session.query(MaterialChunk).filter(
        MaterialChunk.material_id == material.id
    ).delete()
    chunks = split_chunks(text)
    for seq, chunk in enumerate(chunks):
        db.session.add(
            MaterialChunk(
                material_id=material.id,
                seq=seq,
                text=chunk,
                stems=" ".join(sorted(set(stems(chunk)))),
            )
        )
    return len(chunks)


def rank(query, candidates, limit):
    """Лучшие фрагменты для запроса. candidates - пары (данные, строка с основами)."""
    wanted = set(stems(query))
    if not wanted or not candidates:
        return []
    sets = [(item, set(s.split())) for item, s in candidates]
    total = len(sets)
    weight = {}
    for term in wanted:
        df = sum(1 for _, s in sets if term in s)
        weight[term] = math.log(1 + total / (1 + df)) if df else 0.0
    scored = []
    for item, stem_set in sets:
        score = sum(weight[t] for t in wanted if t in stem_set)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored[:limit]]


def search(query, category_id=None, limit=4):
    """Фрагменты материалов, подходящие под запрос. Материалы категории и общие (без категории)."""
    stmt = (
        select(MaterialChunk.text, Material.title, MaterialChunk.stems)
        .join(Material, Material.id == MaterialChunk.material_id)
        .limit(MAX_CANDIDATES)
    )
    if category_id is not None:
        stmt = stmt.where(
            or_(Material.category_id == category_id, Material.category_id.is_(None))
        )
    rows = db.session.execute(stmt).all()
    found = rank(query, [((text, title), stem) for text, title, stem in rows], limit)
    return [{"material": title, "text": text} for text, title in found]


def context_for(category, hints="", limit=3, budget=1800):
    """Выдержки из материалов для запроса к модели или пустая строка."""
    query = f"{category.name} {hints or ''}"
    parts, used = [], 0
    for hit in search(query, getattr(category, "id", None), limit):
        text = hit["text"][: max(budget - used, 0)]
        if not text:
            break
        parts.append(f"[{hit['material']}] {text}")
        used += len(text)
    return "\n".join(parts)
