import json

from arm_api.services import card_schema, seed


def classifier():
    with open(seed.CLASSIFIER_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def test_classifier_is_imported_from_the_official_file():
    data = classifier()
    names = {g["name"] for g in data["groups"]}
    assert (
        len(data["groups"]) == 23
        and sum(len(g["types"]) for g in data["groups"]) > 1000
    )
    assert {"Пожары и задымления", "ДТП", "Запах газа"} <= names
    assert all(len(t["name"]) <= 128 for g in data["groups"] for t in g["types"])


def test_category_codes_fit_the_column_and_are_unique():
    codes = [
        f"G{gi:02d}.{ti:04d}"
        for gi, g in enumerate(classifier()["groups"], 1)
        for ti in range(1, len(g["types"]) + 1)
    ]
    assert len(codes) == len(set(codes)) and max(map(len, codes)) <= 32


def test_card_template_is_consistent():
    keys = [f["key"] for f in card_schema.TEMPLATE_FIELDS]
    assert len(keys) == len(set(keys))
    assert {
        "incident_type",
        "address_street",
        "address_house",
        "description",
        "services",
    } <= set(keys)
    assert set(card_schema.DEFAULT_ACTIONS) <= set(card_schema.ACTION_TYPES)
    assert card_schema.DEFAULT_ACTIONS[-1] == "save_card"


def test_demo_scenarios_match_the_classifier_and_the_template():
    type_names = {t["name"].lower() for g in classifier()["groups"] for t in g["types"]}
    keys = {f["key"] for f in card_schema.TEMPLATE_FIELDS}
    for item in seed.DEMO:
        assert item["category"].lower() in type_names, item["category"]
        assert set(item["card"]) <= keys
        assert item["legend"]["dialog"] and item["legend"]["followups"]


def test_default_settings_are_all_known_scopes():
    from arm_api.models import SettingScope

    scopes = {s.value for s in SettingScope}
    assert all(scope in scopes for _, scope, *_ in card_schema.DEFAULT_SETTINGS)
