"""
GET  /system/updates              - история примененных пакетов обновления
POST /system/updates              - загрузка пакета (multipart, поле file)
POST /system/updates?dry_run=1    - только проверка: что будет добавлено и что не так

Формат пакета и ограничения - в services/updates.py. Пакет применяется целиком или
никак, только при свежей резервной копии и когда не идет ни одно занятие.
"""

import hashlib
import os
import uuid as uuid_mod
from datetime import datetime, timezone

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from flask import Blueprint, current_app, request
from sqlalchemy import func, select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import require, write_audit
from ..models import (
    IncidentCategory,
    Material,
    SessionStatus,
    SystemSetting,
    SystemUpdate,
    TrainingSession,
)
from ..services import knowledge, updates
from ..services.backup import require_recent_backup
from ._helpers import commit, ok
from .scenarios import _active_template, add_imported, parse_import_items
from .system import _settings_updates

updates_bp = Blueprint("updates", __name__)

MIME_BY_EXT = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "json": "application/json",
    "csv": "text/csv",
    "xml": "application/xml",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "txt": "text/plain",
}


@updates_bp.get("/system/updates")
def list_updates():
    require("system.manage")
    stmt = select(SystemUpdate).order_by(SystemUpdate.applied_at.desc())
    return ok(paginate(stmt, serializer=lambda u: u.to_dict()))


def _json_file(files, name, what):
    import json

    try:
        return json.loads(files[name].decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError("Пакет не применен", 422, details={what: "не корректный JSON"})


def _plan_scenarios(contents, files, errors):
    data = _json_file(files, updates.safe_name(contents["scenarios"]), "scenarios")
    items = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        errors["scenarios"] = 'ожидается {"scenarios": [...]}'
        return None
    parsed, item_errors = parse_import_items(items)
    if item_errors:
        errors["scenarios"] = item_errors
    return parsed


def _plan_materials(contents, files, errors):
    known_categories = {
        c.code: c.id for c in db.session.execute(select(IncidentCategory)).scalars()
    }
    result = []
    for index, entry in enumerate(contents.get("materials", [])):
        name = updates.safe_name(entry["file"])
        content = files[name]
        checksum = hashlib.sha256(content).hexdigest()
        code = entry.get("category_code")
        if code and code not in known_categories:
            errors[f"materials[{index}]"] = f"неизвестная категория {code}"
            continue
        duplicate = db.session.execute(
            select(Material.id).where(Material.checksum == checksum).limit(1)
        ).first()
        result.append(
            {
                "title": entry["title"].strip(),
                "ext": name.rsplit(".", 1)[-1].lower(),
                "content": content,
                "checksum": checksum,
                "category_id": known_categories.get(code),
                "duplicate": duplicate is not None,
            }
        )
    return result


def _plan_settings(contents, files, errors):
    raw = files[updates.safe_name(contents["settings"])]
    try:
        root = SafeET.fromstring(raw)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        errors["settings"] = f"некорректный XML: {str(exc)[:120]}"
        return None
    if root.tag != "settings":
        errors["settings"] = "корневой элемент должен быть <settings>"
        return None
    known = {s.key: s for s in db.session.execute(select(SystemSetting)).scalars()}
    changes, setting_errors = _settings_updates(root, known)
    if setting_errors:
        errors["settings"] = setting_errors
    return {k: v for k, v in changes.items() if known[k].value != v}


def _plan(package):
    """Проверка содержимого пакета без изменения БД. Возвращает (план, ошибки)."""
    contents = package["manifest"]["contents"]
    files = package["files"]
    errors = {}
    plan = {"scenarios": None, "materials": [], "settings": None}
    if "scenarios" in contents:
        plan["scenarios"] = _plan_scenarios(contents, files, errors)
    plan["materials"] = _plan_materials(contents, files, errors)
    if "settings" in contents:
        plan["settings"] = _plan_settings(contents, files, errors)
    return plan, errors


def _summary(plan):
    return {
        "scenarios": len(plan["scenarios"] or []),
        "materials_new": sum(1 for m in plan["materials"] if not m["duplicate"]),
        "materials_skipped_duplicates": sum(
            1 for m in plan["materials"] if m["duplicate"]
        ),
        "settings_changed": sorted((plan["settings"] or {}).keys()),
    }


def _store_material(entry, principal, created_paths):
    base_dir = current_app.config["MATERIALS_DIR"]
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, f"{uuid_mod.uuid4().hex}.{entry['ext']}")
    with open(path, "wb") as handle:
        handle.write(entry["content"])
    created_paths.append(path)
    previous = db.session.execute(
        select(func.max(Material.version)).where(Material.title == entry["title"])
    ).scalar()
    material = Material(
        title=entry["title"],
        mime_type=MIME_BY_EXT[entry["ext"]],
        file_path=path,
        size_bytes=len(entry["content"]),
        checksum=entry["checksum"],
        version=(previous or 0) + 1,
        category_id=entry["category_id"],
        uploaded_by=principal.id,
    )
    db.session.add(material)
    db.session.flush()
    chunks = knowledge.index_material(material)
    material.is_indexed = chunks > 0
    material.indexed_at = datetime.now(timezone.utc) if chunks else None


def _check_not_applied(manifest, checksum):
    same = (
        db.session.execute(
            select(SystemUpdate).where(
                (SystemUpdate.checksum == checksum)
                | (SystemUpdate.version == manifest["version"])
            )
        )
        .scalars()
        .first()
    )
    if same is not None:
        raise ApiError(
            "Этот пакет или версия уже применены",
            409,
            code="already_applied",
            details={
                "version": same.version,
                "applied_at": same.applied_at.isoformat(),
            },
        )


def _check_can_apply():
    """Обновление меняет учебные данные: только вне занятий и после копии (ТЗ)."""
    running = db.session.execute(
        select(func.count())
        .select_from(TrainingSession)
        .where(TrainingSession.status == SessionStatus.RUNNING)
    ).scalar_one()
    if running:
        raise ApiError(
            "Обновление недоступно во время занятий: завершите их и повторите",
            409,
            code="sessions_running",
            details={"running_sessions": running},
        )
    require_recent_backup()


def _apply(plan, manifest, checksum, summary, principal):
    created_paths = []
    try:
        if plan["scenarios"]:
            add_imported(plan["scenarios"], _active_template(), None)
        for entry in plan["materials"]:
            if not entry["duplicate"]:
                _store_material(entry, principal, created_paths)
        for key, value in (plan["settings"] or {}).items():
            setting = db.session.get(SystemSetting, key)
            setting.value = value
            setting.updated_by = principal.id
            setting.updated_at = datetime.now(timezone.utc)
        record = SystemUpdate(
            version=manifest["version"],
            title=manifest.get("title"),
            checksum=checksum,
            summary=summary,
            applied_by=principal.id,
        )
        db.session.add(record)
        write_audit(
            db.session, request, principal, "system.update", "system_update", None,
            {"version": manifest["version"], **summary},
        )  # fmt: skip
        commit()
        return record
    except Exception:
        db.session.rollback()
        for path in created_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        raise


@updates_bp.post("/system/updates")
def apply_update():
    principal = require("system.manage")
    upload = request.files.get("file")
    if upload is None:
        raise ApiError("Пакет не передан (поле file, multipart/form-data)", 422)
    data = upload.read()
    checksum = hashlib.sha256(data).hexdigest()
    dry_run = request.args.get("dry_run", "").lower() in {"1", "true", "yes"}

    try:
        package = updates.read_package(data)
    except updates.PackageError as exc:
        raise ApiError(
            "Пакет непригоден",
            422,
            code="bad_package",
            details={"problems": exc.problems},
        )
    manifest = package["manifest"]
    _check_not_applied(manifest, checksum)

    plan, errors = _plan(package)
    if errors:
        raise ApiError("Пакет не применен", 422, code="bad_package", details=errors)
    summary = _summary(plan)
    if dry_run:
        return ok({"dry_run": True, "version": manifest["version"], "plan": summary})

    _check_can_apply()
    record = _apply(plan, manifest, checksum, summary, principal)
    return ok({"applied": True, **record.to_dict()}, 201)
