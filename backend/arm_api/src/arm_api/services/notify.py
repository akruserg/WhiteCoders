"""Доставка оповещений администратору (ТЗ: система оповещения об ошибках).

Оповещения всегда пишутся в /system/alerts. Дополнительно, если администратор
включил доставку (notify.enabled), уходит сообщение:
  - webhook: POST JSON на адрес внутри контура (мессенджер, Mattermost, свой шлюз);
    в теле есть поле text для мессенджеров и полный объект alert для своих систем;
  - почта: SMTP-сервер учебного контура.
Доставка выключена по умолчанию: контур изолирован, внешних адресов нет.

Отправка идет в фоновом потоке с коротким таймаутом, сбой доставки только пишется в
журнал и никогда не мешает обработке запроса. Повтор сообщения по одному и тому же
оповещению не чаще, чем раз в notify.throttle_min минут.
"""

import logging
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import httpx

from . import settings

logger = logging.getLogger(__name__)

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
TIMEOUT_SEC = 5


def should_notify(severity, details, min_severity, throttle_min, now):
    """Нужно ли слать сообщение: уровень не ниже порога и не было отправки недавно."""
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK.get(min_severity, 1):
        return False
    last = (details or {}).get("notified_at")
    if last:
        try:
            sent = datetime.fromisoformat(last)
        except ValueError:
            return True
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=timezone.utc)
        if now - sent < timedelta(minutes=throttle_min):
            return False
    return True


def format_message(alert):
    marks = {"info": "ИНФО", "warning": "ВНИМАНИЕ", "critical": "СБОЙ"}
    severity = alert.severity.value
    lines = [f"[АРМ-112] {marks.get(severity, severity)}: {alert.title}"]
    lines.append(f"Компонент: {alert.component}. Повторов: {alert.occurrences or 1}.")
    clean = {k: v for k, v in (alert.details or {}).items() if k != "notified_at"}
    if clean:
        lines.append("Подробности: " + ", ".join(f"{k}={v}" for k, v in clean.items()))
    return "\n".join(lines)


def _payload(alert):
    return {"text": format_message(alert), "alert": alert.to_dict()}


def send_webhook(url, payload):
    response = httpx.post(url, json=payload, timeout=TIMEOUT_SEC)
    response.raise_for_status()


def send_email(cfg, subject, body):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = cfg["from"]
    message["To"] = cfg["to"]
    message.set_content(body)
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=TIMEOUT_SEC) as smtp:
        if cfg.get("tls"):
            smtp.starttls()
        smtp.send_message(message)


def deliver(cfg, payload):
    """Отправка по всем настроенным каналам. Возвращает {канал: 'ok' | текст ошибки}."""
    result = {}
    if cfg.get("webhook_url"):
        try:
            send_webhook(cfg["webhook_url"], payload)
            result["webhook"] = "ok"
        except Exception as exc:
            # адрес webhook может содержать ключ доступа: в ответ и журнал он не попадает
            text = str(exc).replace(cfg["webhook_url"], "<webhook>")
            result["webhook"] = f"{type(exc).__name__}: {text}"
    if cfg.get("email_to") and cfg.get("smtp_host"):
        try:
            send_email(
                {
                    "host": cfg["smtp_host"],
                    "port": cfg["smtp_port"],
                    "from": cfg["smtp_from"],
                    "to": cfg["email_to"],
                    "tls": cfg["smtp_tls"],
                },
                payload["text"].splitlines()[0],
                payload["text"],
            )
            result["email"] = "ok"
        except Exception as exc:
            result["email"] = f"{type(exc).__name__}: {exc}"
    return result


def load_config():
    get = settings.get
    return {
        "enabled": bool(get("notify.enabled", False)),
        "min_severity": str(get("notify.min_severity", "warning")),
        "throttle_min": int(get("notify.throttle_min", 15) or 0),
        "webhook_url": str(get("notify.webhook_url", "") or ""),
        "email_to": str(get("notify.email_to", "") or ""),
        "smtp_host": str(get("notify.smtp_host", "") or ""),
        "smtp_port": int(get("notify.smtp_port", 25) or 25),
        "smtp_from": str(get("notify.smtp_from", "arm112@localhost") or ""),
        "smtp_tls": bool(get("notify.smtp_tls", False)),
    }


def _spawn(cfg, payload):
    def run():
        result = deliver(cfg, payload)
        failed = {k: v for k, v in result.items() if v != "ok"}
        if failed:
            logger.warning("оповещение не доставлено: %s", failed)

    threading.Thread(target=run, name="alert-notify", daemon=True).start()


def maybe_notify(alert):
    """Вызывается из raise_alert. Никогда не бросает исключений."""
    try:
        cfg = load_config()
        if not cfg["enabled"] or not (cfg["webhook_url"] or cfg["email_to"]):
            return False
        now = datetime.now(timezone.utc)
        if not should_notify(
            alert.severity.value,
            alert.details,
            cfg["min_severity"],
            cfg["throttle_min"],
            now,
        ):
            return False
        alert.details = {**(alert.details or {}), "notified_at": now.isoformat()}
        _spawn(cfg, _payload(alert))
        return True
    except Exception:
        logger.exception("сбой подготовки оповещения")
        return False


def send_test():
    """Проверка настроек: отправляет тестовое сообщение синхронно и возвращает результат."""
    cfg = load_config()
    text = "[АРМ-112] ПРОВЕРКА: тестовое оповещение администратору"
    payload = {"text": text, "alert": {"title": "Проверка канала оповещений"}}
    if not (cfg["webhook_url"] or (cfg["email_to"] and cfg["smtp_host"])):
        return {"configured": False, "channels": {}}
    return {"configured": True, "channels": deliver(cfg, payload)}
