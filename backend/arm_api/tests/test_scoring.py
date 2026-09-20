from arm_api.services import scoring


def test_similarity_ignores_case_punctuation_and_yo():
    assert scoring.similarity("Ёлка, дом 5.", "елка дом 5") == 1.0


def test_similarity_does_not_forgive_different_numbers():
    assert scoring.similarity("ул. Профсоюзная, д. 12", "ул. Профсоюзная, д. 21") <= 0.5
    assert scoring.similarity("кв. 48", "кв. 84") < scoring.FUZZY_MATCH_THRESHOLD


def test_small_typo_in_text_is_still_a_match():
    assert scoring.similarity("Профсоюзная улица", "Профсоюзная улица.") >= 0.82
    assert scoring.similarity("Профсоюзная", "Профсоюзнаяя") >= 0.82


FIELDS = [
    {"key": "address", "label": "Адрес", "required": True},
    {"key": "threat", "label": "Угроза людям", "required": True},
]
REFERENCE = {"address": "Профсоюзная, 12, кв. 48", "threat": "Да"}


def evaluate(answer, **kwargs):
    defaults = dict(
        template_fields=FIELDS,
        reference_card=REFERENCE,
        reference_actions=[],
        answer=answer,
        actions=[],
        duration_ms=20_000,
        time_limit_sec=30,
    )
    return scoring.evaluate(**{**defaults, **kwargs})


def test_perfect_answer_passes():
    verdict = evaluate(dict(REFERENCE))
    assert verdict.score == 100.0 and verdict.passed and not verdict.errors


def test_missing_required_field_is_reported():
    verdict = evaluate({"address": REFERENCE["address"]})
    kinds = [(e["kind"], e["field_key"]) for e in verdict.errors]
    assert ("missing", "threat") in kinds
    assert (
        verdict.score > 70
    )  # по баллам зачёт, но пропуск обязательного поля его отменяет
    assert not verdict.passed


def test_wrong_house_number_is_a_content_error():
    verdict = evaluate({"address": "Профсоюзная, 21, кв. 48", "threat": "Да"})
    assert any(
        e["kind"] == "content" and e["field_key"] == "address" for e in verdict.errors
    )
    assert not verdict.passed  # ошибка в адресе без профиля тоже не зачёт


def test_timing_overrun_uses_tolerance():
    within = evaluate(dict(REFERENCE), duration_ms=32_000)  # 30 с + 10%
    over = evaluate(dict(REFERENCE), duration_ms=40_000)
    assert not any(e["kind"] == "timing" for e in within.errors)
    assert any(e["kind"] == "timing" for e in over.errors)
    assert over.score < within.score


def test_pass_score_comes_from_caller():
    answer = dict(REFERENCE)
    answer["threat"] = "Да."  # отличие только в оформлении: ошибок нет
    assert evaluate(answer, default_pass_score=10).passed
    assert evaluate(answer, default_pass_score=100).passed
    assert not evaluate(answer, default_pass_score=100, duration_ms=60_000).passed
