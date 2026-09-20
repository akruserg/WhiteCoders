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
