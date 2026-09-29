import io
import json
import zipfile

import pytest

from arm_api.services import updates


def make_zip(files, manifest=None, extra_info=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if manifest is not None:
            archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items():
            archive.writestr(name, data)
        for info, data in extra_info or []:
            archive.writestr(info, data)
    return buffer.getvalue()


def good_manifest(**contents):
    return {
        "format": 1,
        "version": "2026.10.1",
        "title": "Осенний пакет",
        "contents": contents or {"scenarios": "scenarios.json"},
    }


@pytest.mark.parametrize(
    "name, expected",
    [
        ("scenarios.json", "scenarios.json"),
        ("materials/памятка.pdf", "materials/памятка.pdf"),
        ("a/./b.txt", "a/b.txt"),
        ("../evil.txt", None),
        ("a/../../evil.txt", None),
        ("/etc/passwd", None),
        ("C:\\windows\\x", None),
        ("a\\b", None),
        ("", None),
        ("x\x00y", None),
    ],
)
def test_safe_name(name, expected):
    assert updates.safe_name(name) == expected


def test_manifest_validation_reports_every_problem():
    assert updates.validate_manifest(good_manifest()) == []
    assert updates.validate_manifest([]) == ["manifest.json должен быть JSON-объектом"]
    bad = {
        "format": 2,
        "version": "лишний пробел ",
        "title": 5,
        "contents": {
            "scenarios": "../x.json",
            "magic": "x",
            "materials": [
                {"file": "m/a.exe", "title": "x"},
                {"file": "m/b.pdf", "title": "  "},
                "не объект",
            ],
        },
    }
    text = " | ".join(updates.validate_manifest(bad))
    for part in (
        "format",
        "version",
        "title",
        "magic",
        "scenarios",
        "неподдерживаемый тип файла",
        "нужно название",
        "ожидается объект",
    ):
        assert part in text, part
    assert updates.validate_manifest({**good_manifest(), "contents": {}})


def test_read_package_returns_manifest_and_files():
    data = make_zip({"scenarios.json": '{"scenarios": []}'}, good_manifest())
    package = updates.read_package(data)
    assert package["manifest"]["version"] == "2026.10.1"
    assert package["files"]["scenarios.json"] == b'{"scenarios": []}'


def raises(data):
    with pytest.raises(updates.PackageError) as caught:
        updates.read_package(data)
    return " ".join(caught.value.problems)


def test_read_package_rejects_broken_input():
    assert "zip" in raises(b"not a zip")
    assert "manifest.json" in raises(make_zip({"a.txt": "x"}))
    buffer = make_zip({"manifest.json": "{oops"})
    assert "JSON" in raises(buffer)
    assert "нет файла scenarios.json" in raises(make_zip({}, good_manifest()))


def test_read_package_rejects_path_traversal_and_symlinks():
    data = make_zip({"../evil.txt": "x"}, good_manifest())
    assert "небезопасный путь" in raises(data)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(good_manifest()))
        link = zipfile.ZipInfo("scenarios.json")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "/etc/passwd")
    assert "символические" in raises(buffer.getvalue())


def test_read_package_limits_entries_and_size(monkeypatch):
    many = make_zip({f"f{i}.txt": "x" for i in range(5)}, good_manifest())
    monkeypatch.setattr(updates, "MAX_ENTRIES", 3)
    assert "больше 3 файлов" in raises(many)
    monkeypatch.setattr(updates, "MAX_ENTRIES", 1000)
    monkeypatch.setattr(updates, "MAX_FILE_BYTES", 10)
    big = make_zip({"scenarios.json": "x" * 50}, good_manifest())
    assert "размер" in raises(big)
