"""
GET    /workstations                   - рабочие места (АРМ)
POST   /workstations                   - создать
GET    /workstations/{id}              - карточка
PATCH  /workstations/{id}              - изменить
DELETE /workstations/{id}              - удалить
GET    /workstations/{id}/config.xml   - конфигурация одного рабочего места в XML
GET    /workstations/export.xml        - все рабочие места одним XML-файлом
POST   /workstations/import            - загрузка XML (создает и обновляет по номеру)
GET    /me/workstation                 - настройки рабочего места текущего обучающегося

Формат XML (версия 1):
<workstations version="1">
  <workstation number="4" name="АРМ 4" ip="10.0.99.4" location="Класс 2" user="petrova" active="true">
    <config>
      <audio><input>default</input><output>default</output><headset type="boolean">true</headset></audio>
      <softphone><mode>webrtc</mode><autoanswer type="boolean">false</autoanswer></softphone>
      <ui><language>ru</language><font_scale type="number">1.0</font_scale></ui>
    </config>
  </workstation>
</workstations>
"""

import copy

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from flask import Blueprint, Response, request
from sqlalchemy import select
from xml.etree import ElementTree as ET

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import current_user, require, write_audit
from ..core.xmlapi import XmlError, element_to_json, to_element
from ..models import User, Workstation
from ..schemas import WorkstationIn, WorkstationUpdate
from ._helpers import body, commit, get_or_404, ok, provided_fields

workstations_bp = Blueprint("workstations", __name__)

MAX_XML_BYTES = 2_000_000

DEFAULT_CONFIG = {
    "audio": {"input": "default", "output": "default", "headset": True, "volume": 80},
    "softphone": {"mode": "webrtc", "autoanswer": False},
    "ui": {"language": "ru", "font_scale": 1.0, "timer_visible": True, "high_contrast": False},
}  # fmt: skip

_SECTIONS = {"audio", "softphone", "ui", "network", "notes"}


# правила проверки: раздел -> поле -> (вид, параметры)
_RULES = {
    "audio": {"headset": ("bool",), "volume": ("range", 0, 100)},
    "softphone": {"mode": ("choice", ("webrtc", "sip")), "autoanswer": ("bool",)},
    "ui": {
        "language": ("choice", ("ru",)),
        "font_scale": ("range", 0.5, 3),
        "timer_visible": ("bool",),
        "high_contrast": ("bool",),
    },
}


def _rule_error(rule, value):
    kind = rule[0]
    if kind == "bool":
        return None if isinstance(value, bool) else "ожидается true или false"
    if kind == "choice":
        return None if value in rule[1] else "допустимо: " + ", ".join(rule[1])
    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if number and rule[1] <= value <= rule[2]:
        return None
    return f"число от {rule[1]} до {rule[2]}"


def validate_config(config):
    """Ошибки настроек рабочего места в виде {поле: сообщение}."""
    if not isinstance(config, dict):
        return {"config": "ожидается объект"}
    errors = {
        name: f"неизвестный раздел (допустимо: {sorted(_SECTIONS)})"
        for name in config
        if name not in _SECTIONS
    }
    for section, rules in _RULES.items():
        values = config.get(section, {})
        if not isinstance(values, dict):
            errors[section] = "ожидается объект"
            continue
        for field, rule in rules.items():
            if field in values:
                message = _rule_error(rule, values[field])
                if message:
                    errors[f"{section}.{field}"] = message
    return errors


def _checked_config(config):
    errors = validate_config(config)
    if errors:
        raise ApiError("Некорректная конфигурация рабочего места", 422, details=errors)
    return config


def _effective_config(station):
    """Настройки по умолчанию, поверх них настройки рабочего места."""
    merged = copy.deepcopy(DEFAULT_CONFIG)
    for section, values in (station.config if station else {}).items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


def _user_by_id(user_id):
    if user_id is None:
        return None
    return get_or_404(User, user_id, "Пользователь")


def _station_element(station):
    node = ET.Element(
        "workstation",
        number=str(station.number),
        name=station.name,
        active="true" if station.is_active else "false",
    )
    if station.ip:
        node.set("ip", station.ip)
    if station.location:
        node.set("location", station.location)
    if station.user:
        node.set("user", station.user.username)
    node.append(to_element(_effective_config(station), "config"))
    return node


def _xml_response(root, filename):
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(
        xml,
        mimetype="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@workstations_bp.get("/workstations")
def list_workstations():
    require("workstation.manage")
    return ok(paginate(select(Workstation).order_by(Workstation.number)))


@workstations_bp.post("/workstations")
def create_workstation():
    principal = require("workstation.manage")
    payload = body(WorkstationIn)
    if db.session.execute(
        select(Workstation.id).where(Workstation.number == payload.number)
    ).first():
        raise ApiError("Рабочее место с таким номером уже есть", 409)
    station = Workstation(
        number=payload.number,
        name=payload.name,
        ip=payload.ip,
        location=payload.location,
        user_id=_user_by_id(payload.user_id).id if payload.user_id else None,
        is_active=payload.is_active,
        config=_checked_config(payload.config),
    )
    db.session.add(station)
    db.session.flush()
    write_audit(
        db.session, request, principal, "workstation.create", "workstation", station.id
    )
    commit()
    return ok(station.to_dict(), 201)


@workstations_bp.get("/workstations/<uuid:station_id>")
def get_workstation(station_id):
    require("workstation.manage")
    return ok(get_or_404(Workstation, station_id, "Рабочее место").to_dict())


@workstations_bp.patch("/workstations/<uuid:station_id>")
def update_workstation(station_id):
    principal = require("workstation.manage")
    station = get_or_404(Workstation, station_id, "Рабочее место")
    payload = body(WorkstationUpdate)
    for name in provided_fields() & {"name", "ip", "location", "is_active"}:
        setattr(station, name, getattr(payload, name))
    if "number" in provided_fields() and payload.number != station.number:
        if db.session.execute(
            select(Workstation.id).where(Workstation.number == payload.number)
        ).first():
            raise ApiError("Рабочее место с таким номером уже есть", 409)
        station.number = payload.number
    if "user_id" in provided_fields():
        station.user_id = _user_by_id(payload.user_id).id if payload.user_id else None
    if "config" in provided_fields():
        station.config = _checked_config(payload.config)
    write_audit(
        db.session, request, principal, "workstation.update", "workstation", station.id
    )
    commit()
    return ok(station.to_dict())


@workstations_bp.delete("/workstations/<uuid:station_id>")
def delete_workstation(station_id):
    principal = require("workstation.manage")
    station = get_or_404(Workstation, station_id, "Рабочее место")
    db.session.delete(station)
    write_audit(
        db.session, request, principal, "workstation.delete", "workstation", station_id
    )
    commit()
    return ok({"status": "deleted"})


@workstations_bp.get("/workstations/<uuid:station_id>/config.xml")
def workstation_config_xml(station_id):
    require("workstation.manage")
    station = get_or_404(Workstation, station_id, "Рабочее место")
    root = ET.Element("workstations", version="1")
    root.append(_station_element(station))
    return _xml_response(root, f"workstation-{station.number}.xml")


@workstations_bp.get("/workstations/export.xml")
def export_workstations_xml():
    require("workstation.manage")
    root = ET.Element("workstations", version="1")
    for station in db.session.execute(
        select(Workstation).order_by(Workstation.number)
    ).scalars():
        root.append(_station_element(station))
    return _xml_response(root, "arm112-workstations.xml")


def _parse_stations(raw):
    if not raw or len(raw) > MAX_XML_BYTES:
        raise ApiError("Ожидается XML размером до 2 МБ", 422)
    try:
        root = SafeET.fromstring(raw)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise ApiError("Некорректный XML", 422, details={"error": str(exc)[:200]})
    if root.tag != "workstations":
        raise ApiError("Корневой элемент должен быть <workstations>", 422)
    return root.findall("workstation")


def _station_from_node(node, users):
    """Один <workstation> -> (значения, ошибки)."""
    errors = {}
    try:
        number = int(node.get("number", ""))
    except ValueError:
        errors["number"] = "целое число"
        number = None
    name = (node.get("name") or "").strip()
    if not name:
        errors["name"] = "обязательный атрибут"
    username = node.get("user")
    if username and username not in users:
        errors["user"] = f"пользователь {username!r} не найден"
    config = {}
    config_node = node.find("config")
    if config_node is not None:
        try:
            config = element_to_json(config_node)
        except XmlError as exc:
            errors["config"] = str(exc)
        if isinstance(config, str):  # пустой <config/>
            config = {}
        if not errors.get("config"):
            errors.update(
                {f"config.{k}": v for k, v in validate_config(config).items()}
            )
    values = {
        "number": number,
        "name": name,
        "ip": node.get("ip"),
        "location": node.get("location"),
        "user_id": users.get(username),
        "is_active": (node.get("active", "true").lower() != "false"),
        "config": config,
    }
    return values, errors


@workstations_bp.post("/workstations/import")
def import_workstations_xml():
    """Пакетная загрузка XML: создает новые рабочие места и обновляет по номеру.
    Применяется целиком или не применяется вовсе."""
    principal = require("workstation.manage")
    nodes = _parse_stations(request.get_data())
    if not nodes:
        raise ApiError("В файле нет ни одного <workstation>", 422)

    users = {u.username: u.id for u in db.session.execute(select(User)).scalars()}
    existing = {s.number: s for s in db.session.execute(select(Workstation)).scalars()}
    parsed, errors, seen = [], {}, set()
    for index, node in enumerate(nodes):
        values, node_errors = _station_from_node(node, users)
        if values["number"] in seen:
            node_errors["number"] = "номер повторяется в файле"
        seen.add(values["number"])
        if node_errors:
            errors[str(index)] = node_errors
        else:
            parsed.append(values)
    if errors:
        raise ApiError("XML не применен", 422, details=errors)

    created = updated = 0
    for values in parsed:
        station = existing.get(values["number"])
        if station is None:
            db.session.add(Workstation(**values))
            created += 1
        else:
            for key, value in values.items():
                setattr(station, key, value)
            updated += 1
    write_audit(
        db.session, request, principal, "workstation.import", "workstation", None,
        {"created": created, "updated": updated},
    )  # fmt: skip
    commit()
    return ok({"created": created, "updated": updated}, 201)


@workstations_bp.get("/me/workstation")
def my_workstation():
    """Настройки рабочего места, закрепленного за пользователем (по умолчанию - типовые)."""
    principal = current_user()
    station = (
        db.session.execute(
            select(Workstation).where(
                Workstation.user_id == principal.id, Workstation.is_active.is_(True)
            )
        )
        .scalars()
        .first()
    )
    return ok(
        {
            "workstation": station.to_dict() if station else None,
            "config": _effective_config(station),
        }
    )
