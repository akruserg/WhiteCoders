import zipfile

from arm_api.services import ai, knowledge


def test_stems_ignore_case_endings_and_stopwords():
    a = knowledge.stems("Пожарные направлены в квартиру")
    b = knowledge.stems("пожарный направить квартира")
    assert "пожар" in a and "кварт" in a and "в" not in a
    assert set(a) & set(b) >= {"пожар", "кварт"}
    assert knowledge.stems("Ёлка") == knowledge.stems("елка")


def test_split_chunks_respects_limit_and_keeps_all_text():
    text = "Первый абзац.\n\n" + ("Длинное предложение без конца " * 60) + "\n\nТретий."
    chunks = knowledge.split_chunks(text, size=200)
    assert all(len(c) <= 200 for c in chunks)
    joined = " ".join(chunks)
    assert "Первый абзац." in joined and "Третий." in joined


def test_rank_prefers_chunks_with_rare_query_words():
    docs = [
        ("про газ", "газ утечк запах"),
        ("про пожар", "пожар дым квартир"),
        ("про воду", "вод труб прорыв"),
    ]
    found = knowledge.rank("утечка газа в квартире", docs, limit=2)
    assert found[0] == "про газ"
    assert knowledge.rank("совсем другое слово", docs, limit=2) == []
    assert knowledge.rank("", docs, limit=2) == []


def test_docx_text_is_extracted_without_third_party_libraries(tmp_path):
    path = tmp_path / "памятка.docx"
    xml = (
        '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>'
        "<w:p><w:r><w:t>При утечке газа</w:t></w:r><w:r><w:t> не включать свет.</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Вызвать службу 104.</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    text = knowledge.extract_text(str(path), "docx")
    assert "При утечке газа не включать свет." in text and "службу 104" in text


def test_text_formats_json_csv_xml_txt_and_audio(tmp_path):
    (tmp_path / "a.json").write_text('{"k": ["газ", {"x": "дым"}]}', encoding="utf-8")
    (tmp_path / "a.csv").write_text("код;название\n104;Газ\n", encoding="utf-8")
    (tmp_path / "a.xml").write_text("<r><i>вода</i><i>труба</i></r>", encoding="utf-8")
    (tmp_path / "a.txt").write_bytes("Пожар".encode("cp1251"))
    assert "газ" in knowledge.extract_text(str(tmp_path / "a.json"), "json")
    assert "104" in knowledge.extract_text(str(tmp_path / "a.csv"), "csv")
    assert "труба" in knowledge.extract_text(str(tmp_path / "a.xml"), "xml")
    assert knowledge.extract_text(str(tmp_path / "a.txt"), "txt") == "Пожар"
    assert knowledge.extract_text("x.mp3", "mp3") == ""


def test_xml_with_entities_is_rejected(tmp_path):
    bomb = '<!DOCTYPE r [<!ENTITY a "x">]><r>&a;</r>'
    (tmp_path / "b.xml").write_text(bomb, encoding="utf-8")
    try:
        knowledge.extract_text(str(tmp_path / "b.xml"), "xml")
    except Exception as exc:
        assert "ntit" in type(exc).__name__ or "ntit" in str(exc)
    else:
        raise AssertionError("XML с сущностями должен отклоняться")


def test_scenario_prompt_gets_materials_context():
    from types import SimpleNamespace as NS

    category = NS(name="Утечка газа", code="04.01")
    fields = [{"key": "description", "label": "Описание"}]
    plain = ai._scenario_prompt(category, 2, fields, "")
    with_ctx = ai._scenario_prompt(
        category, 2, fields, "", context="[Памятка] Не включать свет."
    )
    assert "Памятка" not in plain
    assert "Не включать свет" in with_ctx


def test_broken_knowledge_base_does_not_break_generation():
    def boom(category):
        raise RuntimeError("БД недоступна")

    assert ai._safe_context(boom, object()) == ""
    assert ai._safe_context(None, object()) == ""
    assert ai._safe_context(lambda c: "текст", object()) == "текст"
