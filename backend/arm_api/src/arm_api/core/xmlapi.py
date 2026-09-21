"""XML как второй формат обмена (совместимость с legacy-системами по API).

Любая точка API принимает тело запроса в XML (Content-Type: application/xml или
text/xml) и отдает ответ в XML, если клиент попросил его заголовком
`Accept: application/xml` или параметром `?format=xml`. Внутри приложение всегда
работает с теми же структурами, что и для JSON, поэтому правил валидации одни.

Соответствие JSON и XML (имя корневого элемента при разборе игнорируется):

    {"a": "текст"}          <a>текст</a>
    {"n": 1.5}              <n type="number">1.5</n>
    {"ok": true}            <ok type="boolean">true</ok>
    {"x": null}             <x nil="true"/>
    {"list": [1, "два"]}    <list type="array"><item type="number">1</item><item>два</item></list>
    {"obj": {"k": "v"}}     <obj><k>v</k></obj>

Простые запросы старых систем без атрибутов тоже разбираются:
<request><username>ivan</username><password>secret</password></request>
"""

import json
import re
from collections import Counter
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from flask import Request, request

XML_MIMETYPES = {"application/xml", "text/xml"}
_NAME = re.compile(r"^[^\W\d][\w.\-]*$", re.UNICODE)
_INVALID_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
MAX_XML_BYTES = 8 * 1024 * 1024


class XmlError(ValueError):
    """Некорректный XML во входящем запросе."""


# ------------------------------------------------------------------ JSON -> XML


def _text(value):
    return _INVALID_CHARS.sub("", str(value))


def _fill(element, value):
    if value is None:
        element.set("nil", "true")
    elif isinstance(value, bool):
        element.set("type", "boolean")
        element.text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        element.set("type", "number")
        element.text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, (list, tuple)):
        element.set("type", "array")
        for item in value:
            _fill(ET.SubElement(element, "item"), item)
    elif isinstance(value, dict):
        for key, item in value.items():
            name = str(key)
            if _NAME.match(name):
                child = ET.SubElement(element, name)
            else:  # ключ, невозможный как имя элемента, передаем атрибутом
                child = ET.SubElement(element, "field", name=_text(name))
            _fill(child, item)
    else:
        element.text = _text(value)


def to_element(value, tag="response"):
    root = ET.Element(tag)
    _fill(root, value)
    return root


def json_to_xml(value, tag="response"):
    return ET.tostring(to_element(value, tag), encoding="utf-8", xml_declaration=True)


# ------------------------------------------------------------------ XML -> JSON


def _number(text):
    try:
        return int(text)
    except ValueError:
        return float(text)


def _scalar(element, kind, text):
    if kind == "boolean":
        if text.lower() not in {"true", "false", "1", "0"}:
            raise XmlError(f"<{element.tag}>: ожидается true или false")
        return text.lower() in {"true", "1"}
    try:
        return _number(text)
    except ValueError:
        raise XmlError(f"<{element.tag}>: ожидается число")


def element_to_json(element):
    if element.get("nil") == "true":
        return None
    kind = element.get("type")
    children = list(element)
    if kind == "array":
        return [element_to_json(child) for child in children]
    if kind in {"boolean", "number"}:
        return _scalar(element, kind, (element.text or "").strip())
    if not children:
        return element.text or ""

    pairs = []
    for child in children:
        named = child.tag == "field" and child.get("name")
        pairs.append(
            (child.get("name") if named else child.tag, element_to_json(child))
        )
    repeated = {key for key, count in Counter(k for k, _ in pairs).items() if count > 1}
    result = {}
    for key, value in pairs:
        if key in repeated:  # повтор одноименных элементов - массив
            result.setdefault(key, []).append(value)
        else:
            result[key] = value
    return result


def xml_to_json(raw):
    """Разбор входящего XML (защита от XXE и сущностей). Ошибка - XmlError."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_XML_BYTES:
        raise XmlError("XML слишком большой")
    try:
        root = SafeET.fromstring(raw)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise XmlError(f"Некорректный XML: {str(exc)[:150]}") from exc
    return element_to_json(root)


# ------------------------------------------------------------------ Flask


class XmlAwareRequest(Request):
    """request.get_json() понимает тело в XML, остальной код об этом не знает."""

    def get_json(self, force=False, silent=False, cache=True):
        if self.mimetype not in XML_MIMETYPES:
            return super().get_json(force=force, silent=silent, cache=cache)
        if "_xml_json" not in self.__dict__:
            try:
                self.__dict__["_xml_json"] = xml_to_json(self.get_data())
            except XmlError:
                if not silent:
                    raise
                return None
        return self.__dict__["_xml_json"]


def wants_xml():
    if request.args.get("format", "").lower() == "xml":
        return True
    best = request.accept_mimetypes.best_match(
        ["application/json", "application/xml", "text/xml"]
    )
    # JSON выигрывает, если клиент не указал явного предпочтения XML
    return best in XML_MIMETYPES and request.accept_mimetypes[best] > (
        request.accept_mimetypes["application/json"]
    )


def convert_response(response):
    """XML-ответ вместо JSON, если клиент попросил XML."""
    if response.mimetype != "application/json" or not wants_xml():
        return response
    try:
        payload = json.loads(response.get_data(as_text=True))
    except ValueError:
        return response
    response.set_data(json_to_xml(payload))
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    response.vary.add("Accept")
    return response


def validate_xml_body():
    """До обработчика: битый XML в теле - 400, а не «обязательное поле»."""
    if request.mimetype in XML_MIMETYPES and request.method in {"POST", "PUT", "PATCH"}:
        if request.path.rstrip("/").endswith(
            ("/settings/import", "/workstations/import")
        ):
            return None  # эти точки сами разбирают XML и отвечают подробнее
        try:
            request.get_json()
        except XmlError as exc:
            from .errors import error_response

            return error_response(str(exc), 400, code="invalid_xml")
    return None
