import hashlib
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import select
from sqlalchemy.engine.url import make_url

from ..core.extensions import db
from ..core.security import log_event
from ..models import Backup

logger = logging.getLogger(__name__)

KIND_FULL = "full"
KIND_INCREMENTAL = "incremental"


def _now():
    return datetime.now(timezone.utc)


def _backups_dir():
    configured = current_app.config.get("BACKUPS_DIR")
    if configured:
        path = configured
    else:
        reports = current_app.config["REPORTS_DIR"]
        path = os.path.join(os.path.dirname(reports) or "/var/lib/arm112", "backups")
    os.makedirs(path, exist_ok=True)
    return path


def _pg_dump_command(file_path):
    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    command = [
        "pg_dump",
        "--format=custom",
        "--file",
        file_path,
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username or "postgres",
        "--dbname",
        url.database,
    ]
    return command, env


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dump_database(file_path):
    if shutil.which("pg_dump") is None:
        raise RuntimeError("pg_dump недоступен в контейнере API")
    command, env = _pg_dump_command(file_path)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        timeout=1800,
        env=env,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            stderr or f"pg_dump завершился с кодом {completed.returncode}"
        )


def _prune_old_backups():
    """Удаляет файлы старых копий, оставляя BACKUPS_KEEP последних."""
    keep = int(current_app.config.get("BACKUPS_KEEP", 30))
    old = (
        db.session.execute(
            select(Backup)
            .where(Backup.status == "success", Backup.file_path.is_not(None))
            .order_by(Backup.started_at.desc())
            .offset(keep)
        )
        .scalars()
        .all()
    )
    for backup in old:
        try:
            os.remove(backup.file_path)
        except OSError:
            pass
        backup.file_path = None
        backup.error = "файл удален по политике хранения"


def run_backup(kind="full", automatic=True, created_by=None):
    kind = kind if kind in {KIND_FULL, KIND_INCREMENTAL} else KIND_FULL
    backup = Backup(
        kind=kind,
        is_automatic=automatic,
        created_by=created_by,
        status="running",
    )
    db.session.add(backup)
    db.session.flush()

    target_dir = _backups_dir()
    path = os.path.join(target_dir, f"backup_{backup.id}.dump")

    try:
        _dump_database(path)
        backup.status = "success"
        backup.file_path = path
        backup.size_bytes = os.path.getsize(path)
        backup.checksum = _file_sha256(path)
        backup.error = None
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
        backup.status = "failed"
        backup.error = str(exc)[:1000]
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    backup.finished_at = _now()
    if backup.status == "success":
        _prune_old_backups()

    log_event(
        "backup",
        "info" if backup.status == "success" else "error",
        f"Резервная копия {backup.id}: {backup.status}",
        {
            "kind": kind,
            "automatic": automatic,
            "size_bytes": backup.size_bytes,
        },
    )
    db.session.commit()
    return backup


def has_successful_automatic_backup_since(since):
    return (
        db.session.execute(
            select(Backup.id)
            .where(
                Backup.is_automatic.is_(True),
                Backup.status == "success",
                Backup.started_at >= since,
            )
            .limit(1)
        ).first()
        is not None
    )


def run_daily_backup_if_due():
    since = _now() - timedelta(hours=24)
    if has_successful_automatic_backup_since(since):
        logger.info("Ежедневный бэкап пропущен: успешная копия уже есть за 24 часа")
        return None
    return run_backup(kind=KIND_FULL, automatic=True)


def _seconds_until_next_run(hour):
    now = _now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


def run_loop():
    from arm_api import app

    hour = int(app.config.get("BACKUP_HOUR_UTC", 3))
    logger.info("Планировщик бэкапов запущен, слот %02d:00 UTC", hour)
    with app.app_context():
        try:
            run_daily_backup_if_due()
        except Exception:
            logger.exception("Стартовый бэкап завершился ошибкой")
    while True:
        delay = _seconds_until_next_run(hour)
        logger.info("Следующий бэкап через %.0f с", delay)
        time.sleep(delay)
        with app.app_context():
            try:
                run_daily_backup_if_due()
            except Exception:
                logger.exception("Ежедневный бэкап завершился ошибкой")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    run_loop()
