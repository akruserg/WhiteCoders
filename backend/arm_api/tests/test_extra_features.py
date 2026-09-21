import importlib.util
import os
from types import SimpleNamespace

import pytest
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from arm_api.models import User
from arm_api.routes import sessions as sessions_routes
from arm_api.services import card_schema, grammar, reporting, seed


def issues(text, **kwargs):
    return grammar.check_text(text, "f", kwargs.get("rules"))


# ---------------------------------------------------------------- орфография


def test_spelling_flags_unknown_word_and_suggests_fix():
    found = [i for i in issues("Сообшение принято") if "орфограф" in i["message"]]
    assert len(found) == 1
    assert found[0]["actual"] == "Сообшение" and found[0]["expected"] == "сообщение"


def test_correct_inflected_forms_are_not_flagged():
    text = "Дежурная бригада направлена, сантехники приступили к работе на пятом этаже."
    assert not [i for i in issues(text) if "орфограф" in i["message"]]


def test_abbreviations_names_and_scenario_words_are_ignored():
    assert not [i for i in issues("Вызов принят от МЧС") if "орфограф" in i["message"]]
    assert not [
        i
        for i in issues("Заявитель Иванов сообщил о дыме")
        if "орфограф" in i["message"]
    ]
    rules = {"known_words": grammar.words_of("улица Вороновское шоссе")}
    text = "адрес вороновское шоссе"
    assert [i for i in issues(text) if "орфограф" in i["message"]] != []
    assert not [
        i for i in grammar.check_text(text, "f", rules) if "орфограф" in i["message"]
    ]


def test_spelling_can_be_switched_off_and_is_limited_to_three():
    assert not [
        i
        for i in issues("Сообшение", rules={"spelling": False})
        if "орфограф" in i["message"]
    ]
    many = "Ааааа Бббббб вввввв гггггг дддддд ееееее жжжжжж"
    assert len([i for i in issues(many) if "орфограф" in i["message"]]) <= 3


# ---------------------------------------------------------------- обезличивание отчетов


def test_namer_numbers_users_consistently_and_hides_names():
    namer = reporting.Namer(anonymize=True)
    assert namer.name("u1", "Петрова Анна") == "Обучающийся 1"
    assert namer.name("u2", "Смирнов Дмитрий") == "Обучающийся 2"
    assert namer.name("u1", "Петрова Анна") == "Обучающийся 1"
    assert namer.login("u2", "umc_smirnov") == "Обучающийся 2"


def test_namer_is_transparent_by_default():
    assert reporting.Namer().name("u1", "Петрова Анна") == "Петрова Анна"


# ---------------------------------------------------------------- XML настроек


def test_xml_parser_rejects_entity_bombs_and_external_entities():
    bomb = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><settings>&b;</settings>'
    external = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><settings>&e;</settings>'
    for payload in (bomb, external):
        with pytest.raises(DefusedXmlException):
            SafeET.fromstring(payload)
    assert (
        SafeET.fromstring("<settings><setting key='a'>1</setting></settings>").tag
        == "settings"
    )


def test_new_routes_are_registered(app):
    rules = {(r.rule, m) for r in app.url_map.iter_rules() for m in r.methods}
    for path, method in [
        ("/api/v1/system/settings/export.xml", "GET"),
        ("/api/v1/system/settings/import", "POST"),
        ("/api/v1/system/services", "GET"),
        ("/api/v1/auth/consent", "POST"),
        ("/api/v1/users/<uuid:user_id>/anonymize", "POST"),
        ("/api/v1/attempts/<uuid:attempt_id>/scenario", "POST"),
        ("/api/v1/attempts/<uuid:attempt_id>/draft", "PUT"),
    ]:
        assert (path, method) in rules, (method, path)


def test_new_endpoints_require_authentication(client):
    assert client.get("/api/v1/system/settings/export.xml").status_code == 401
    assert (
        client.post("/api/v1/system/settings/import", data="<settings/>").status_code
        == 401
    )
    assert client.post("/api/v1/auth/consent").status_code == 401


# ---------------------------------------------------------------- карточка обучающегося -> сценарий


def test_action_types_are_filtered_to_the_known_vocabulary():
    actions = [{"type": "fill_address"}, "save_card", {"type": "выдумано"}, None]
    assert sessions_routes._action_types(actions) == ["fill_address", "save_card"]


def test_answer_values_become_text():
    assert (
        sessions_routes._as_text(["Служба 101", "Служба 103"])
        == "Служба 101, Служба 103"
    )
    assert (
        sessions_routes._as_text(None) == ""
        and sessions_routes._as_text(" 12 ") == "12"
    )


# ---------------------------------------------------------------- данные и настройки


def test_env_backed_settings_exist_in_config_and_defaults(app):
    keys = {s[0] for s in card_schema.DEFAULT_SETTINGS}
    assert set(seed.ENV_BACKED) <= keys
    assert all(name in app.config for name in seed.ENV_BACKED.values())


def test_user_model_has_personal_data_columns():
    assert hasattr(User, "pd_consent_at") and hasattr(User, "anonymized_at")


def test_migration_chain_is_linear():
    base = os.path.join(os.path.dirname(__file__), "..", "migrations", "versions")
    revisions = {}
    for name in os.listdir(base):
        if name.endswith(".py"):
            spec = importlib.util.spec_from_file_location(
                name[:-3], os.path.join(base, name)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            revisions[module.revision] = module.down_revision
    heads = set(revisions) - set(revisions.values())
    assert len(heads) == 1 and list(revisions.values()).count(None) == 1


# ---------------------------------------------------------------- прогноз успеваемости


def test_forecast_needs_three_sessions():
    from arm_api.services import analytics

    result = analytics.forecast_scores([70, 75])
    assert result["available"] is False and result["points"] == 2


def test_forecast_follows_linear_trend():
    from arm_api.services import analytics

    up = analytics.forecast_scores([50, 55, 60, 65])
    assert up["available"] and up["trend"] == "up" and up["next_score"] == 70.0
    assert up["trend_per_session"] == 5.0 and up["r2"] == 1.0
    assert (
        up["sessions_to_pass"] == 1
    )  # последний балл 65, до порога 70 при +5 за занятие
    down = analytics.forecast_scores([90, 80, 70])
    assert (
        down["trend"] == "down"
        and down["next_score"] == 60.0
        and down["sessions_to_pass"] is None
    )
    flat = analytics.forecast_scores([80, 80, 80])
    assert flat["trend"] == "flat" and flat["next_score"] == 80.0


def test_forecast_is_clamped_to_score_range():
    from arm_api.services import analytics

    assert analytics.forecast_scores([80, 90, 100])["next_score"] == 100.0
    assert analytics.forecast_scores([20, 10, 0])["next_score"] == 0.0


# ---------------------------------------------------------------- локация сценария


def test_location_reaches_the_prompt_and_the_legend(app, monkeypatch):
    import json as _json
    import httpx

    from arm_api.services import ai

    seen = []

    def handler(request):
        seen.append(_json.loads(request.content)["messages"][1]["content"])
        scenario = {
            "title": "t",
            "legend": {
                "summary": "s",
                "dialog": ["Горит"],
                "followups": [],
                "hints": [],
            },
            "reference_card": {"address_street": "Мира"},
            "reference_actions": [],
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": _json.dumps(scenario)}}]}
        )

    app.config.update(AI_ENABLED=True)
    ai.settings.get = lambda key, default=None: default
    ai._client = lambda timeout=None: httpx.Client(
        base_url="http://x", transport=httpx.MockTransport(handler)
    )
    cat = SimpleNamespace(id=1, name="пожар", code="G01")
    fields = [{"key": "address_street", "label": "Улица"}]
    with app.app_context():
        drafts = ai.generate_scenarios(
            [cat], count=1, template_fields=fields, location="ТАО, Вороновское"
        )
    assert "ТАО, Вороновское" in seen[0]
    assert drafts[0]["legend"]["location"] == "ТАО, Вороновское"


# ---------------------------------------------------------------- лимит времени


def test_time_limit_priority_session_scenario_profile_default():
    from types import SimpleNamespace as NS

    resolve = sessions_routes.resolve_time_limit
    session = NS(time_limit_sec=20)
    scenario = NS(time_limit_sec=45)
    profile = NS(default_time_limit_sec=60)
    assert resolve(session, scenario, profile, 30) == 20
    assert resolve(NS(time_limit_sec=None), scenario, profile, 30) == 45
    assert resolve(NS(time_limit_sec=None), NS(time_limit_sec=None), profile, 30) == 60
    assert resolve(NS(time_limit_sec=None), NS(time_limit_sec=None), None, 30) == 30


def test_time_limit_is_optional_in_schemas():
    from arm_api import schemas

    for cls in (
        schemas.SessionCreate,
        schemas.ScenarioGenerateIn,
        schemas.ScenarioImportItem,
    ):
        assert cls._fields["time_limit_sec"].default is None
        assert cls._fields["time_limit_sec"].nullable
    assert schemas.GradingProfileIn._fields["default_time_limit_sec"].default == 30


# ---------------------------------------------------------------- матрица прав ролей


def test_default_role_permissions_satisfy_the_rules():
    from arm_api.core import security

    for role, codes in security.ROLE_PERMISSIONS.items():
        assert security.check_role_permissions(role, codes) == [], role


def test_role_rules_block_dangerous_changes():
    from arm_api.core.security import ROLE_PERMISSIONS, check_role_permissions

    teacher = set(ROLE_PERMISSIONS["teacher"])
    assert check_role_permissions("teacher", teacher | {"system.manage"})
    admin = set(ROLE_PERMISSIONS["admin"])
    assert check_role_permissions("admin", admin | {"attempt.grade"})
    assert check_role_permissions("admin", admin - {"user.manage"})
    student = set(ROLE_PERMISSIONS["student"])
    assert check_role_permissions("student", student | {"scenario.manage"})
    assert check_role_permissions("student", student | {"no.such.right"})
    # безопасное расширение допустимо
    assert check_role_permissions("teacher", teacher - {"certificate.issue"}) == []


def test_performance_settings_are_consistent():
    from arm_api.services import card_schema, seed, settings

    keys = {row[0]: row for row in card_schema.DEFAULT_SETTINGS}
    for key in settings.PERF_ENV:
        assert key in keys and key in seed.ENV_BACKED
        assert keys[key][1] == "performance" and keys[key][5] is True  # нужен рестарт
    assert keys["perf.max_active_sessions"][5] is False  # действует сразу
