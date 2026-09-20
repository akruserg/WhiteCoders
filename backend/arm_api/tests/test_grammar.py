from arm_api.services import grammar


def messages(text, **rules):
    return [issue["message"] for issue in grammar.check_text(text, "f", rules or None)]


def test_clean_text_has_no_issues():
    assert messages("Сообщение принято, бригада направлена.") == []


def test_detects_spacing_and_case_problems():
    found = messages("сообщение  принято ,бригада направлена")
    assert "Лишние пробелы между словами" in found
    assert "Пробел перед знаком препинания" in found
    assert "Отсутствует пробел после знака препинания" in found
    assert "Предложение должно начинаться с заглавной буквы" in found


def test_mixed_alphabets_and_brackets():
    assert any("кириллицы и латиницы" in m for m in messages("Привeт"))  # латинская e
    assert "Непарные скобки или кавычки" in messages("Пожар (в доме")


def test_rules_can_be_switched_off_and_empty_is_ignored():
    assert messages("привет  мир", double_space=False, capital_first=False) == []
    assert grammar.check_text("   ") == [] and grammar.check_text(None) == []


def test_issue_order_is_stable():
    kinds = [i["message"] for i in grammar.check_text("привет  мир ,тест тест")]
    assert kinds.index("Лишние пробелы между словами") < kinds.index(
        "Повтор слова «тест»"
    )


def test_only_text_fields_are_checked():
    fields = [{"key": "note", "type": "text"}, {"key": "phone", "type": "phone"}]
    issues = grammar.check_answer(
        {"note": "плохо  написано", "phone": "8  999"}, fields
    )
    assert {i["field_key"] for i in issues} == {"note"}
