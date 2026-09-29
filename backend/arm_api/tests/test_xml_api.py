import json
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from arm_api.core import xmlapi
from arm_api.routes import workstations as ws

SAMPLE = {
    "id": "a1",
    "count": 3,
    "ratio": 0.5,
    "ok": True,
    "missing": None,
    "text": "Сообщение <принято> & передано",
    "tags": ["один", 2, False, None],
    "nested": {"inner": {"k": "v"}, "list": [{"x": 1}, {"x": 2}]},
}


def test_json_survives_a_round_trip_through_xml():
    xml = xmlapi.json_to_xml(SAMPLE)
    assert xml.startswith(b"<?xml")
    assert xmlapi.xml_to_json(xml) == SAMPLE


def test_keys_that_are_not_valid_element_names_are_kept():
    data = {"a b": 1, "1x": "y", "normal": True}
    assert xmlapi.xml_to_json(xmlapi.json_to_xml(data)) == data


def test_simple_legacy_xml_without_type_attributes():
    legacy = "<request><username>ivan</username><password>secret</password></request>"
    assert xmlapi.xml_to_json(legacy) == {"username": "ivan", "password": "secret"}


def test_repeated_elements_become_an_array():
    legacy = "<r><item>1</item><item>2</item><name>x</name></r>"
    assert xmlapi.xml_to_json(legacy) == {"item": ["1", "2"], "name": "x"}


def test_control_characters_are_removed_from_output():
    xml = xmlapi.json_to_xml({"t": "a\x00b\x0bc"})
    assert ET.fromstring(xml).find("t").text == "abc"


@pytest.mark.parametrize(
    "payload, message",
    [
        ("<r><a type='number'>abc</a></r>", "ожидается число"),
        ("<r><a type='boolean'>maybe</a></r>", "ожидается true или false"),
        ("<r><a>", "Некорректный XML"),
        (
            '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><r>&e;</r>',
            "Некорректный XML",
        ),
    ],
)
def test_bad_or_hostile_xml_is_rejected(payload, message):
    with pytest.raises(xmlapi.XmlError, match=message):
        xmlapi.xml_to_json(payload)


def test_openapi_is_available_as_xml_by_accept_header_and_by_parameter(client):
    as_json = client.get("/api/v1/openapi.json")
    assert as_json.mimetype == "application/json"
    for kwargs in (
        {"headers": {"Accept": "application/xml"}},
        {"query_string": {"format": "xml"}},
    ):
        response = client.get("/api/v1/openapi.json", **kwargs)
        assert (
            response.mimetype == "application/xml"
            and response.headers["Vary"] == "Accept"
        )
        assert (
            xmlapi.xml_to_json(response.data)["openapi"]
            == as_json.get_json()["openapi"]
        )


def test_json_stays_the_default_for_wildcard_accept(client):
    assert (
        client.get("/health", headers={"Accept": "*/*"}).mimetype == "application/json"
    )
    assert (
        client.get(
            "/health", headers={"Accept": "application/json, application/xml;q=0.5"}
        ).mimetype
        == "application/json"
    )


def test_xml_request_body_reaches_the_same_validation_as_json(client):
    url = "/api/v1/auth/login"
    body = "<request><username>ivan</username></request>"
    as_xml = client.post(url, data=body, content_type="application/xml")
    as_json = client.post(url, json={"username": "ivan"})
    assert as_xml.status_code == as_json.status_code == 422
    assert (
        as_xml.get_json()["error"]["details"]
        == as_json.get_json()["error"]["details"]
        == {"password": "обязательное поле"}
    )


def test_broken_xml_body_is_a_400_and_errors_can_come_back_as_xml(client):
    response = client.post(
        "/api/v1/auth/login",
        data="<request><username>",
        content_type="text/xml",
        headers={"Accept": "application/xml"},
    )
    assert response.status_code == 400 and response.mimetype == "application/xml"
    assert xmlapi.xml_to_json(response.data)["error"]["code"] == "invalid_xml"


# ---------------------------------------------------------------- рабочие места


def test_config_validation_reports_each_bad_field():
    assert ws.validate_config(ws.DEFAULT_CONFIG) == {}
    errors = ws.validate_config(
        {
            "ui": {"font_scale": 9, "language": "en"},
            "softphone": {"mode": "isdn"},
            "audio": {"headset": "yes"},
            "junk": 1,
        }
    )
    assert set(errors) == {
        "ui.font_scale",
        "ui.language",
        "softphone.mode",
        "audio.headset",
        "junk",
    }
    assert ws.validate_config("x") == {"config": "ожидается объект"}


def test_effective_config_merges_over_defaults():
    station = SimpleNamespace(config={"ui": {"font_scale": 1.5}, "notes": "класс 2"})
    merged = ws._effective_config(station)
    assert merged["ui"]["font_scale"] == 1.5 and merged["ui"]["language"] == "ru"
    assert merged["notes"] == "класс 2" and merged["softphone"]["mode"] == "webrtc"
    assert ws._effective_config(None) == ws.DEFAULT_CONFIG


XML_STATION = """<workstation number="4" name="АРМ 4" ip="10.0.99.4" user="petrova" active="false">
  <config><softphone><mode>sip</mode><autoanswer type="boolean">true</autoanswer></softphone>
  <ui><font_scale type="number">1.25</font_scale></ui></config></workstation>"""


def test_workstation_xml_node_is_parsed_and_validated():
    node = ET.fromstring(XML_STATION)
    values, errors = ws._station_from_node(node, {"petrova": "uid-1"})
    assert errors == {}
    assert (
        values["number"] == 4
        and values["user_id"] == "uid-1"
        and values["is_active"] is False
    )
    assert values["config"]["softphone"] == {"mode": "sip", "autoanswer": True}
    assert values["config"]["ui"]["font_scale"] == 1.25


def test_workstation_xml_errors_are_collected_not_thrown():
    bad = ET.fromstring(
        '<workstation number="x" user="ghost"><config><ui><font_scale type="number">10</font_scale></ui></config></workstation>'
    )
    _, errors = ws._station_from_node(bad, {})
    assert {"number", "name", "user", "config.ui.font_scale"} <= set(errors)


def test_exported_station_xml_can_be_imported_back():
    station = SimpleNamespace(
        number=7,
        name="АРМ 7",
        is_active=True,
        ip="10.0.0.7",
        location="Класс 1",
        user=SimpleNamespace(username="stud1"),
        config={"ui": {"font_scale": 2.0}},
    )
    node = ws._station_element(station)
    values, errors = ws._station_from_node(
        ET.fromstring(ET.tostring(node)), {"stud1": "u"}
    )
    assert errors == {} and values["number"] == 7 and values["ip"] == "10.0.0.7"
    assert (
        values["config"]["ui"]["font_scale"] == 2.0
        and values["config"]["softphone"]["mode"] == "webrtc"
    )


def test_new_workstation_routes_need_authentication(client):
    assert client.get("/api/v1/workstations").status_code == 401
    assert (
        client.post(
            "/api/v1/workstations/import",
            data="<workstations/>",
            content_type="application/xml",
        ).status_code
        == 401
    )
    assert client.get("/api/v1/me/workstation").status_code == 401
    assert (
        json.loads(client.get("/api/v1/workstations").data)["error"]["code"]
        == "unauthenticated"
    )
