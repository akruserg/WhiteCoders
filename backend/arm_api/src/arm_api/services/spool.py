"""Буфер данных при временных сбоях базы данных (ТЗ: предотвращение потери).

Пока БД недоступна, ответы обучающегося (черновик и отправка карточки) не
теряются: запрос проверяется по подписи токена, записывается на диск (запись
атомарная, с fsync) и подтверждается ответом 202. Как только БД возвращается,
фоновая служба обрабатывает записи по порядку получения и удаляет их.

    python -m arm_api.services.spool run       # служба повторной обработки
    python -m arm_api.services.spool replay    # разовая обработка
    python -m arm_api.services.spool status    # сколько записей ждет

Отправка обрабатывается с временем ПОЛУЧЕНИЯ ответа: сбой БД не съедает норматив
времени у обучающегося. Повторная обработка идемпотентна: уже оцененная карточка
не оценивается второй раз.
"""

import argparse
import fcntl
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from flask import current_app
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from ..core.errors import ApiError

logger = logging.getLogger(__name__)

KINDS = {"draft", "submit"}
# endpoint Flask -> вид записи: только эти операции можно принять без БД
BUFFERABLE = {"sessions.save_draft": "draft", "sessions.submit_card": "submit"}


class SpoolFull(RuntimeError):
    """Буфер переполнен: принимать новые записи нельзя."""


def is_db_outage(exc):
    """Ошибка означает недоступность БД (обрыв, отказ соединения), а не баг запроса."""
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    return isinstance(exc, DBAPIError) and bool(exc.connection_invalidated)


def _dir(sub=""):
    path = os.path.join(current_app.config["SPOOL_DIR"], sub)
    os.makedirs(path, exist_ok=True)
    return path


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(directory, name, payload):
    tmp = os.path.join(directory, f".{name}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, os.path.join(directory, name))
    _fsync_dir(directory)


def pending_files():
    directory = _dir()
    return sorted(
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".json") and not f.startswith(".")
    )


def status():
    failed_dir = _dir("failed")
    return {
        "pending": len(pending_files()),
        "failed": len([f for f in os.listdir(failed_dir) if f.endswith(".json")]),
    }


def enqueue(kind, attempt_id, user_id, answer, actions, request_meta):
    """Записывает ответ обучающегося в буфер. Возвращает описание записи."""
    if kind not in KINDS:
        raise ValueError(f"неизвестный вид записи: {kind}")
    if len(pending_files()) >= current_app.config["SPOOL_MAX_FILES"]:
        raise SpoolFull("Буфер переполнен")
    received = datetime.now(timezone.utc)
    entry_id = uuid.uuid4().hex
    entry = {
        "id": entry_id,
        "kind": kind,
        "attempt_id": str(attempt_id),
        "user_id": str(user_id),
        "received_at": received.isoformat(),
        "answer": answer,
        "actions": actions,
        "ip": request_meta.get("ip"),
        "user_agent": request_meta.get("user_agent"),
    }
    # имя начинается со времени получения: порядок обработки = порядок получения
    _write_atomic(
        _dir(), f"{int(received.timestamp() * 1000):015d}-{entry_id}.json", entry
    )
    return {"id": entry_id, "kind": kind, "received_at": entry["received_at"]}


# ------------------------------------------------------------------ повторная обработка


class Rejected(Exception):
    """Запись обработать нельзя и не нужно повторять (причина сохраняется)."""


class Obsolete(Exception):
    """Запись устарела: результат уже получен другим путем."""


def _apply(entry):
    from ..core.extensions import db
    from ..models import Attempt, AttemptStatus, TrainingSession, User
    from ..routes.sessions import process_submission

    user = db.session.get(User, uuid.UUID(entry["user_id"]))
    if user is None or not user.is_active or user.is_blocked:
        raise Rejected("учетная запись недоступна")
    attempt = db.session.get(
        Attempt, uuid.UUID(entry["attempt_id"]), with_for_update=True
    )
    if attempt is None or attempt.user_id != user.id:
        raise Rejected("карточка не найдена или принадлежит другому пользователю")

    received = datetime.fromisoformat(entry["received_at"])
    status_now = attempt.status
    if status_now in {AttemptStatus.SUBMITTED, AttemptStatus.EVALUATED}:
        raise Obsolete("карточка уже отправлена")
    if status_now is AttemptStatus.EXPIRED:
        session = db.session.get(TrainingSession, attempt.session_id)
        finished = session.finished_at if session else None
        if entry["kind"] == "submit" and finished and received <= finished:
            attempt.status = AttemptStatus.IN_PROGRESS  # успел до завершения занятия
        else:
            raise Rejected("занятие завершено до получения ответа")
    if attempt.status is not AttemptStatus.IN_PROGRESS:
        raise Rejected("вызов по карточке не был принят")

    if entry["kind"] == "draft":
        attempt.answer, attempt.actions = entry["answer"], entry["actions"]
        return None
    request_shim = SimpleNamespace(
        headers={
            "X-Real-IP": entry.get("ip") or "",
            "User-Agent": entry.get("user_agent") or "",
        },
        remote_addr=entry.get("ip"),
    )
    return process_submission(
        attempt, user, entry["answer"], entry["actions"], received, request_shim
    )


def _quarantine(path, entry, reason):
    entry["rejected_reason"] = reason
    entry["rejected_at"] = datetime.now(timezone.utc).isoformat()
    _write_atomic(_dir("failed"), os.path.basename(path), entry)
    os.remove(path)


def replay_all():
    """Обрабатывает буфер. Возвращает {"done", "obsolete", "rejected", "left"}."""
    from ..core.extensions import db
    from ..core.security import log_event
    from ..services import alerts, integrations

    result = {"done": 0, "obsolete": 0, "rejected": 0, "left": 0}
    lock_path = os.path.join(_dir(), ".replay.lock")
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:  # другая служба уже обрабатывает буфер
            result["left"] = len(pending_files())
            return result
        for path in pending_files():
            with open(path, encoding="utf-8") as handle:
                entry = json.load(handle)
            try:
                hangup_id = _apply(entry)
                db.session.commit()
            except Obsolete:
                db.session.rollback()
                os.remove(path)
                result["obsolete"] += 1
                continue
            except Rejected as exc:
                db.session.rollback()
                _quarantine(path, entry, str(exc))
                log_event(
                    "spool",
                    "warning",
                    f"Запись буфера отклонена: {exc}",
                    {"entry": entry["id"]},
                )
                alerts.raise_alert(
                    "spool", "Запись из буфера не обработана", "spool.rejected", "warning",
                    {"entry": entry["id"], "reason": str(exc)},
                )  # fmt: skip
                db.session.commit()
                result["rejected"] += 1
                continue
            except Exception as exc:
                db.session.rollback()
                if is_db_outage(exc):
                    break  # БД еще недоступна: остальное подождет
                logger.exception("Запись буфера %s: непредвиденная ошибка", entry["id"])
                _quarantine(path, entry, f"ошибка обработки: {exc}")
                result["rejected"] += 1
                continue
            os.remove(path)
            result["done"] += 1
            integrations.hangup(hangup_id)
    result["left"] = len(pending_files())
    return result


# ------------------------------------------------------------------ прием без БД


def outage_response(request):
    """Ответ на запрос, для которого БД недоступна: (тело, код, заголовки).

    Ответы обучающегося принимаются в буфер (202), остальное получает 503 с
    Retry-After. Подпись токена проверяется без БД, права берутся из токена;
    полную проверку (владелец карточки, состояние) делает повторная обработка.
    """
    from ..core.security import decode_token, _bearer_token
    from ..schemas import SubmitIn, ValidationError

    headers = {"Retry-After": str(current_app.config["SPOOL_RETRY_AFTER_SEC"])}
    kind = BUFFERABLE.get(request.endpoint)
    unavailable = (
        {
            "code": "db_unavailable",
            "message": "База данных временно недоступна, повторите запрос",
        },
        503,
    )
    if kind is None:
        return unavailable[0], unavailable[1], headers

    claims = decode_token(_bearer_token(), "access")  # ApiError 401 при плохом токене
    if "attempt.submit" not in claims.get("perms", []):
        raise ApiError("Недостаточно прав для операции", 403, code="forbidden")
    try:
        payload = SubmitIn.from_request()
    except ValidationError as exc:
        raise ApiError(
            "Ошибка валидации данных", 422, code="validation_error", details=exc.errors
        )
    try:
        info = enqueue(
            kind,
            request.view_args["attempt_id"],
            claims["sub"],
            payload.answer,
            payload.actions,
            {
                "ip": request.headers.get("X-Real-IP") or request.remote_addr,
                "user_agent": request.headers.get("User-Agent"),
            },
        )
    except (SpoolFull, OSError) as exc:
        logger.error("Буфер недоступен: %s", exc)
        return unavailable[0], unavailable[1], headers
    body = {
        "status": "buffered",
        "buffer_id": info["id"],
        "kind": kind,
        "attempt_id": str(request.view_args["attempt_id"]),
        "received_at": info["received_at"],
        "message": "База данных временно недоступна: ответ принят в буфер и будет обработан автоматически",
    }
    return body, 202, headers


# ------------------------------------------------------------------ служба


def run_loop(interval=None):
    from arm_api import app

    interval = interval or app.config["SPOOL_REPLAY_INTERVAL_SEC"]
    logger.info("Служба буфера запущена, период %s с", interval)
    while True:
        try:
            with app.app_context():
                if pending_files():
                    outcome = replay_all()
                    if outcome["done"] or outcome["rejected"]:
                        logger.info("Буфер обработан: %s", outcome)
        except Exception:
            logger.exception("Сбой цикла буфера")
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Буфер данных при сбоях БД")
    parser.add_argument("command", choices=["run", "replay", "status"])
    args = parser.parse_args()
    if args.command == "run":
        run_loop()
        return
    from arm_api import app

    with app.app_context():
        print(
            json.dumps(
                replay_all() if args.command == "replay" else status(),
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
