import json
from types import SimpleNamespace

import httpx
import pytest

from arm_api.services import ai, card_schema, scoring

FIELDS = [
    f
    for f in card_schema.TEMPLATE_FIELDS
    if f["key"] in {"incident_type", "address_street", "victims", "services"}
]
CATEGORIES = [
    SimpleNamespace(id=1, name="пожар: квартира", code="G01.0001"),
    SimpleNamespace(id=2, name="ДТП", code="G02.0001"),
]


def completion(payload):
    body = (
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    )
    return {"choices": [{"message": {"content": body}}]}


SCENARIO = {
    "title": "Пожар на кухне",
    "legend": {
        "summary": "Дым на кухне",
        "dialog": ["Горит кухня!", " "],
        "followups": ["Улица Мира, 5"],
        "hints": ["Уточнить адрес"],
    },
    "reference_card": {
        "incident_type": "пожар: квартира",
        "address_street": "улица Мира",
        "victims": "Нет",
        "services": ["Служба 101", "Служба 103"],
        "лишнее": "x",
    },
    "reference_actions": ["fill_address", "выдуманное_действие", "save_card"],
}


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Настройки в проде читаются из БД, в тестах берем значения по умолчанию."""
    monkeypatch.setattr(ai.settings, "get", lambda key, default=None: default)


@pytest.fixture
def llm(app, monkeypatch):
    """Включенный ИИ и подмена сервера модели. Запросы к модели копятся в llm.requests."""
    app.config.update(AI_ENABLED=True, AI_SCORING_ENABLED=True)
    state = SimpleNamespace(
        requests=[],
        reply=lambda request: httpx.Response(200, json=completion(SCENARIO)),
    )

    def handler(request):
        state.requests.append(json.loads(request.content))
        return state.reply(request)

    monkeypatch.setattr(
        ai,
        "_client",
        lambda timeout=None: httpx.Client(
            base_url="http://llm.test", transport=httpx.MockTransport(handler)
        ),
    )
    with app.app_context():
        yield state
    app.config.update(AI_ENABLED=False, AI_SCORING_ENABLED=False)


def test_generation_returns_clean_drafts_bound_to_categories(llm):
    drafts = ai.generate_scenarios(
        CATEGORIES, count=2, difficulty=3, template_fields=FIELDS
    )
    assert [d["category_id"] for d in drafts] == [1, 2]  # категории по кругу
    draft = drafts[0]
    assert set(draft["reference_card"]) == {
        f["key"] for f in FIELDS
    }  # лишнее поле отброшено
    assert (
        draft["reference_card"]["services"] == "Служба 101, Служба 103"
    )  # список -> строка
    assert draft["reference_actions"] == [
        "fill_address",
        "save_card",
    ]  # выдуманное действие отброшено
    assert draft["legend"]["dialog"] == ["Горит кухня!"]  # пустая реплика убрана
    assert draft["difficulty"] == 3 and draft["ai_model"]


def test_generation_constrains_output_with_json_schema(llm):
    ai.generate_scenarios(CATEGORIES[:1], count=1, template_fields=FIELDS)
    schema = llm.requests[0]["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]["reference_card"]["required"]) == {
        f["key"] for f in FIELDS
    }
    assert (
        schema["properties"]["reference_actions"]["items"]["enum"]
        == card_schema.ACTION_TYPES
    )
    roles = [m["role"] for m in llm.requests[0]["messages"]]
    assert roles == ["system", "user"]


def test_generation_is_capped_per_request(llm, app):
    app.config["AI_MAX_SCENARIOS_PER_REQUEST"] = 2
    try:
        assert (
            len(ai.generate_scenarios(CATEGORIES, count=50, template_fields=FIELDS))
            == 2
        )
    finally:
        app.config["AI_MAX_SCENARIOS_PER_REQUEST"] = 5


def test_unavailable_model_gives_503_error(llm):
    llm.reply = lambda request: httpx.Response(500, text="oom")
    with pytest.raises(ai.AiUnavailable) as info:
        ai.generate_scenarios(CATEGORIES, count=1, template_fields=FIELDS)
    assert info.value.status == 503 and info.value.code == "ai_unavailable"


def test_model_answer_with_noise_around_json_is_parsed(llm):
    llm.reply = lambda request: httpx.Response(
        200, json=completion("Вот сценарий: " + json.dumps(SCENARIO) + " Удачи!")
    )
    assert ai.generate_scenarios(CATEGORIES[:1], count=1, template_fields=FIELDS)


def test_disabled_module_refuses(app):
    app.config["AI_ENABLED"] = False
    with app.app_context():
        assert ai.is_enabled() is False and ai.model_name() == "disabled"
        with pytest.raises(ai.AiUnavailable):
            ai.generate_scenarios(CATEGORIES, count=1, template_fields=FIELDS)
        patch, explanation = ai.apply_correction(scenario_obj(), "поправь")
        assert patch == {} and "отключен" in explanation


def scenario_obj():
    return SimpleNamespace(
        legend={
            "summary": "s",
            "dialog": ["Горит"],
            "followups": [],
            "hints": [],
            "audio": "fire",
        },
        reference_card={
            "incident_type": "пожар: квартира",
            "address_street": "Мира",
            "victims": "Нет",
            "services": "Служба 101",
        },
        reference_actions=["fill_address", "save_card"],
    )


def test_correction_returns_only_real_changes_and_keeps_audio(llm):
    changed = {
        "explanation": "Добавлена служба 104",
        "legend": {"summary": "s", "dialog": ["Горит"], "followups": [], "hints": []},
        "reference_card": {
            "incident_type": "пожар: квартира",
            "address_street": "Мира",
            "victims": "Нет",
            "services": "Служба 101, Служба 104",
        },
        "reference_actions": ["fill_address", "save_card"],
    }
    llm.reply = lambda request: httpx.Response(200, json=completion(changed))
    patch, explanation = ai.apply_correction(scenario_obj(), "добавь службу 104")
    assert set(patch) == {"reference_card"}  # легенда и действия не менялись
    assert patch["reference_card"]["services"] == "Служба 101, Служба 104"
    assert explanation == "Добавлена служба 104"


def test_correction_survives_model_failure(llm):
    llm.reply = lambda request: httpx.Response(503)
    patch, explanation = ai.apply_correction(scenario_obj(), "поправь")
    assert patch == {} and "недоступен" in explanation


ROWS = (
    [("missing", "victims")] * 4 + [("timing", None)] * 2 + [("grammar", "description")]
)


def test_insight_falls_back_to_rules_without_model(app):
    with app.app_context():
        result = ai.build_group_insight(ROWS, "ДДС-А")
    assert result["ai_model"] == ai.RULES_MODEL
    assert (
        "пропуски обязательных полей: 4" in result["body"]
        and "victims" in result["body"]
    )
    assert result["data"]["total"] == 7 and 0 < result["confidence"] < 1
    assert result["title"].endswith("ДДС-А")


def test_insight_uses_model_and_never_sends_student_name(llm):
    llm.reply = lambda request: httpx.Response(
        200,
        json=completion(
            {
                "summary": "Часто пропускают поля.",
                "recommendations": ["Проверять карточку"],
            }
        ),
    )
    result = ai.build_student_recommendation({"avg_score": 71}, ROWS, "Петрова Анна")
    assert (
        result["ai_model"] == ai.model_name()
        and "Часто пропускают поля." in result["body"]
    )
    assert "Петрова" not in json.dumps(
        llm.requests[0], ensure_ascii=False
    )  # ПДн не уходят в модель
    assert "Петрова" in result["title"]


def test_insight_falls_back_when_model_fails(llm):
    llm.reply = lambda request: httpx.Response(500)
    assert ai.build_group_insight(ROWS)["ai_model"] == ai.RULES_MODEL


def test_semantic_judge_true_false_and_failure(llm):
    llm.reply = lambda request: httpx.Response(
        200, json=completion({"equivalent": True})
    )
    assert ai.semantic_equal("Описание", "Пожар в квартире", "Горит квартира") is True
    llm.reply = lambda request: httpx.Response(
        200, json=completion({"equivalent": False})
    )
    assert ai.semantic_equal("Описание", "Пожар", "ДТП") is False
    llm.reply = lambda request: httpx.Response(500)
    assert ai.semantic_equal("Описание", "Пожар", "ДТП") is None
    assert llm.requests[0]["temperature"] == 0  # проверка детерминирована


def test_caller_turn_returns_model_reply(llm):
    llm.reply = lambda request: httpx.Response(
        200, json=completion({"reply": "Пятый этаж, подъезд слева"})
    )
    legend = {"summary": "Пожар в квартире", "dialog": ["Помогите, пожар!"]}
    history = [{"author": "operator", "text": "Адрес?"}]
    reply = ai.caller_turn(legend, history, "На каком этаже?", turn=1)
    assert reply == "Пятый этаж, подъезд слева"
    assert llm.requests[0]["messages"][1]["role"] == "user"


def test_caller_turn_raises_when_reply_is_empty(llm):
    llm.reply = lambda request: httpx.Response(200, json=completion({"reply": "  "}))
    with pytest.raises(ai.AiUnavailable):
        ai.caller_turn({}, [], "Алло?")


def test_caller_turn_raises_when_model_disabled(app):
    with app.app_context():
        with pytest.raises(ai.AiUnavailable):
            ai.caller_turn({}, [], "Алло?")


def test_judge_turns_paraphrase_into_match_but_never_touches_numbers_or_types():
    fields = [
        {"key": "description", "label": "Описание", "type": "textarea"},
        {"key": "phone", "label": "Телефон", "type": "phone"},
    ]
    reference = {"description": "Задымление в квартире", "phone": "+7 495 111-22-33"}
    answer = {"description": "В квартире идет дым", "phone": "+7 495 111-22-34"}
    calls = []

    def judge(label, expected, actual):
        calls.append(label)
        return True

    ratio, errors, stats = scoring.score_content(fields, reference, answer, judge=judge)
    assert calls == ["Описание"]  # телефон судье не показываем
    assert stats["semantic_matches"] == 1
    assert [e["field_key"] for e in errors] == ["phone"]


def test_judge_call_count_is_limited():
    fields = [{"key": f"f{i}", "label": f"Поле {i}", "type": "text"} for i in range(8)]
    reference = {f"f{i}": "совершенно другой текст ответа" for i in range(8)}
    answer = {f"f{i}": f"ничего общего {i}" for i in range(8)}
    calls = []
    scoring.score_content(
        fields, reference, answer, judge=lambda *a: calls.append(a) or False
    )
    assert len(calls) == scoring.MAX_JUDGE_CALLS
