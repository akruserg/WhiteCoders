"""
GET  /system/health            - состояние компонентов в реальном времени
GET  /system/metrics           - нагрузка и показатели работоспособности
GET  /system/settings          - параметры (VoIP, бэкапы, логирование, ИИ)
PUT  /system/settings/{key}    - изменение параметра
GET  /system/audit             - журнал аудита действий пользователей
GET  /system/audit/verify      - проверка целостности журнала (цепочка хэшей)
GET  /system/events            - системный журнал
GET  /system/alerts            - оповещения об ошибках и сбоях
POST /system/alerts/{id}/ack | /resolve
GET  /system/backups           - история резервных копий
POST /system/backups           - запуск резервного копирования
GET  /system/voip              - состояние VoIP (Asterisk)
POST /system/services/{name}/{action} - запуск/остановка сервисов
"""

import os
import shutil
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, request
from sqlalchemy import func, select, text

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import audit_entry_hash, require, write_audit
from ..models import (
    Alert,
    AlertStatus,
    Attempt,
    AttemptStatus,
    AuditLog,
    Backup,
    SettingScope,
    SystemEvent,
    SystemSetting,
    TrainingSession,
    SessionStatus,
)
from ..schemas import AlertActionIn, BackupCreateIn, SettingUpdateIn
from ..services import ai, integrations, reporting
from ..services.backup import run_backup
from ._helpers import body, commit, get_or_404, item, ok, uuid_arg

system_bp = Blueprint("system", __name__)

MANAGED_SERVICES = ("api", "voip", "ai", "scheduler")


def _db_state():
    started = datetime.now(timezone.utc)
    try:
        db.session.execute(text("SELECT 1"))
        latency = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        return {"status": "up", "latency_ms": round(latency, 2)}
    except Exception as exc:
        return {"status": "down", "error": str(exc)[:200]}


def _voip_state():
    if not integrations.voip_available():
        return {"status": "disabled"}
    health = integrations.voip_health()
    return {
        "status": "up" if health.get("available") else "down",
        "max_latency_ms": current_app.config["VOIP_MAX_LATENCY_MS"],
        "pool": health.get("pool"),
        "error": health.get("error"),
    }


def _ai_state():
    if not ai.is_enabled():
        return {"status": "disabled"}
    state = ai.health()
    return {
        "status": "up" if state.get("available") else "down",
        "model": state.get("model"),
        "error": state.get("error"),
    }


@system_bp.get("/system/health")
def health():
    require("system.monitor")
    database = _db_state()
    components = {
        "api": {"status": "up"},
        "database": database,
        "voip": _voip_state(),
        "ai": _ai_state(),
        "reports": {"status": "up", "formats": reporting.available_formats()},
    }
    overall = (
        "up"
        if all(c["status"] in {"up", "disabled"} for c in components.values())
        else "degraded"
    )
    return ok(
        {
            "status": overall,
            "server_time": datetime.now(timezone.utc).isoformat(),
            "components": components,
        }
    )


@system_bp.get("/system/metrics")
def metrics():
    require("system.monitor")
    active_sessions = db.session.execute(
        select(func.count(TrainingSession.id)).where(
            TrainingSession.status == SessionStatus.RUNNING
        )
    ).scalar_one()
    active_attempts = db.session.execute(
        select(func.count(Attempt.id)).where(
            Attempt.status.in_([AttemptStatus.ISSUED, AttemptStatus.IN_PROGRESS])
        )
    ).scalar_one()
    open_alerts = db.session.execute(
        select(func.count(Alert.id)).where(Alert.status != AlertStatus.RESOLVED)
    ).scalar_one()

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    errors_24h = db.session.execute(
        select(func.count(SystemEvent.id)).where(
            SystemEvent.ts >= since,
            SystemEvent.level.in_(["error", "critical"]),
        )
    ).scalar_one()

    disk = shutil.disk_usage(os.path.dirname(current_app.config["REPORTS_DIR"]) or "/")
    return ok(
        {
            "active_sessions": active_sessions,
            "concurrent_attempts": active_attempts,
            "capacity": {
                "max_users": 100,
                "max_concurrent_sessions": 20,
                "voip_latency_limit_ms": current_app.config["VOIP_MAX_LATENCY_MS"],
            },
            "open_alerts": open_alerts,
            "errors_24h": errors_24h,
            "database": _db_state(),
            "disk": {
                "total_gb": round(disk.total / 2**30, 1),
                "free_gb": round(disk.free / 2**30, 1),
            },
            "load_avg": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        }
    )


@system_bp.get("/system/settings")
def list_settings():
    principal = require("system.manage", "system.monitor")
    stmt = select(SystemSetting).order_by(SystemSetting.scope, SystemSetting.key)
    if request.args.get("scope"):
        try:
            stmt = stmt.where(
                SystemSetting.scope == SettingScope(request.args["scope"])
            )
        except ValueError:
            raise ApiError("Некорректный scope", 422)
    rows = list(db.session.execute(stmt).scalars())
    reveal = (
        principal.role.code == "admin" and request.args.get("reveal_secrets") == "1"
    )
    return ok(
        {
            "items": [row.to_dict(reveal_secret=reveal) for row in rows],
            "total": len(rows),
        }
    )


@system_bp.put("/system/settings/<path:key>")
def update_setting(key):
    principal = require("system.manage")
    setting = get_or_404(SystemSetting, key, "Параметр")
    payload = body(SettingUpdateIn)

    old_value = setting.value
    setting.value = payload.value
    setting.updated_by = principal.id
    setting.updated_at = datetime.now(timezone.utc)

    write_audit(
        db.session,
        request,
        principal,
        "setting.update",
        "system_setting",
        key,
        {
            "old": None if setting.is_secret else old_value,
            "new": None if setting.is_secret else payload.value,
        },
    )
    commit()
    return ok({**setting.to_dict(), "restart_required": setting.requires_restart})


@system_bp.get("/system/audit")
def audit_log():
    require("audit.read")
    stmt = select(AuditLog).order_by(AuditLog.ts.desc())
    if uuid_arg("user_id"):
        stmt = stmt.where(AuditLog.user_id == uuid_arg("user_id"))
    if request.args.get("action"):
        stmt = stmt.where(AuditLog.action == request.args["action"])
    if request.args.get("object_type"):
        stmt = stmt.where(AuditLog.object_type == request.args["object_type"])
    if request.args.get("since"):
        try:
            since = datetime.fromisoformat(request.args["since"])
        except ValueError:
            raise ApiError("since должен быть датой ISO 8601", 422)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        stmt = stmt.where(AuditLog.ts >= since)
    return ok(paginate(stmt))


@system_bp.get("/system/audit/verify")
def verify_audit():
    require("audit.read")
    try:
        limit = min(max(int(request.args.get("limit", 1000)), 1), 10000)
    except ValueError:
        raise ApiError("limit должен быть целым числом", 422)
    entries = list(
        db.session.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        ).scalars()
    )[::-1]

    broken, tampered = [], []
    previous = None
    for entry in entries:
        if previous is not None and entry.prev_hash != previous.entry_hash:
            broken.append(entry.id)  # цепочка разорвана: запись удалена или вставлена
        if audit_entry_hash(entry) != entry.entry_hash:
            tampered.append(entry.id)  # содержимое записи изменено
        previous = entry
    return ok(
        {
            "checked": len(entries),
            "broken_links": broken,
            "tampered": tampered,
            "intact": not broken and not tampered,
        }
    )


@system_bp.get("/system/events")
def system_events():
    require("system.monitor")
    stmt = select(SystemEvent).order_by(SystemEvent.ts.desc())
    if request.args.get("level"):
        stmt = stmt.where(SystemEvent.level == request.args["level"])
    if request.args.get("component"):
        stmt = stmt.where(SystemEvent.component == request.args["component"])
    return ok(paginate(stmt))


@system_bp.get("/system/alerts")
def list_alerts():
    require("system.monitor")
    stmt = select(Alert).order_by(Alert.last_seen_at.desc())
    if request.args.get("status"):
        try:
            stmt = stmt.where(Alert.status == AlertStatus(request.args["status"]))
        except ValueError:
            raise ApiError("Некорректный status", 422)
    return ok(paginate(stmt))


@system_bp.post("/system/alerts/<int:alert_id>/ack")
def ack_alert(alert_id):
    principal = require("system.manage")
    alert = get_or_404(Alert, alert_id, "Оповещение")
    body(AlertActionIn)
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_by = principal.id
    alert.acknowledged_at = datetime.now(timezone.utc)
    write_audit(db.session, request, principal, "alert.ack", "alert", alert_id)
    commit()
    return item(alert)


@system_bp.post("/system/alerts/<int:alert_id>/resolve")
def resolve_alert(alert_id):
    principal = require("system.manage")
    alert = get_or_404(Alert, alert_id, "Оповещение")
    body(AlertActionIn)
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = datetime.now(timezone.utc)
    write_audit(db.session, request, principal, "alert.resolve", "alert", alert_id)
    commit()
    return item(alert)


@system_bp.get("/system/backups")
def list_backups():
    require("system.manage", "system.monitor")
    return ok(paginate(select(Backup).order_by(Backup.started_at.desc())))


@system_bp.post("/system/backups")
def create_backup():
    principal = require("system.manage")
    payload = body(BackupCreateIn)
    backup = run_backup(kind=payload.kind, automatic=False, created_by=principal.id)
    write_audit(
        db.session,
        request,
        principal,
        "backup.create",
        "backup",
        backup.id,
        {"status": backup.status, "kind": backup.kind},
    )
    commit()
    if backup.status == "failed":
        return ok(backup.to_dict(), 202)
    return item(backup, 201)


@system_bp.get("/system/voip")
def voip_status():
    require("system.monitor")
    return ok(integrations.voip_health())


def _set_voip_enabled(principal, enabled):
    """Включатель VoIP хранится в БД, чтобы его видели все воркеры API."""
    setting = db.session.get(SystemSetting, integrations.VOIP_SETTING_KEY)
    if setting is None:
        setting = SystemSetting(
            key=integrations.VOIP_SETTING_KEY,
            scope=SettingScope.VOIP,
            description="Принудительно включить или выключить VoIP-звонки",
            default_value=current_app.config["VOIP_ENABLED"],
        )
        db.session.add(setting)
    setting.value = enabled
    setting.updated_by = principal.id


@system_bp.post("/system/services/<service>/<action>")
def manage_service(service, action):
    principal = require("system.manage")
    if service not in MANAGED_SERVICES:
        raise ApiError(f"Неизвестный сервис. Доступны: {list(MANAGED_SERVICES)}", 404)
    if action not in {"start", "stop", "restart"}:
        raise ApiError("Допустимые действия: start, stop, restart", 422)
    if service == "api" and action in {"stop", "restart"}:
        raise ApiError(
            "Остановка API выполняется средствами оркестратора, а не через сам API",
            409,
        )

    if service != "voip":
        raise ApiError(
            f"Сервисом «{service}» управляет оркестратор (docker compose), "
            "из API он не запускается и не останавливается",
            501,
            code="not_implemented",
        )

    enabled = action != "stop"
    _set_voip_enabled(principal, enabled)
    details = {"voip_enabled": enabled, "available": integrations.voip_available()}

    db.session.add(
        SystemEvent(
            component=service,
            level="info",
            message=f"Команда {action} для сервиса {service}",
            details=details,
        )
    )
    write_audit(
        db.session, request, principal, f"service.{action}", "service", service, details
    )
    commit()
    return ok({"service": service, "action": action, "details": details})
