from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from arm_api.models import AlertSeverity
from arm_api.services import notify

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def alert(severity="critical", details=None):
    return NS(
        severity=AlertSeverity(severity),
        title="Сбой резервного копирования",
        component="backup",
        occurrences=2,
        details=details or {},
        to_dict=lambda: {"title": "Сбой резервного копирования"},
    )


def test_severity_threshold():
    assert notify.should_notify("critical", {}, "warning", 15, NOW)
    assert notify.should_notify("warning", {}, "warning", 15, NOW)
    assert not notify.should_notify("info", {}, "warning", 15, NOW)
    assert not notify.should_notify("warning", {}, "critical", 15, NOW)


def test_throttle_blocks_repeats_within_the_window_only():
    recent = {"notified_at": (NOW - timedelta(minutes=5)).isoformat()}
    old = {"notified_at": (NOW - timedelta(minutes=30)).isoformat()}
    assert not notify.should_notify("critical", recent, "warning", 15, NOW)
    assert notify.should_notify("critical", old, "warning", 15, NOW)
    assert notify.should_notify(
        "critical", {"notified_at": "мусор"}, "warning", 15, NOW
    )
    naive = {
        "notified_at": (NOW - timedelta(minutes=1)).replace(tzinfo=None).isoformat()
    }
    assert not notify.should_notify("critical", naive, "warning", 15, NOW)


def test_message_is_readable_and_hides_service_fields():
    text = notify.format_message(
        alert(details={"elapsed_sec": 41.2, "notified_at": "2026-09-21T12:00:00"})
    )
    assert text.startswith("[АРМ-112] СБОЙ: Сбой резервного копирования")
    assert "backup" in text and "Повторов: 2" in text and "elapsed_sec=41.2" in text
    assert "notified_at" not in text


def test_webhook_gets_text_and_full_alert(monkeypatch):
    sent = []
    monkeypatch.setattr(
        notify, "send_webhook", lambda url, body: sent.append((url, body))
    )
    cfg = {"webhook_url": "http://gw.local/hook"}
    result = notify.deliver(cfg, notify._payload(alert()))
    assert result == {"webhook": "ok"}
    assert sent[0][0] == "http://gw.local/hook"
    assert "СБОЙ" in sent[0][1]["text"] and sent[0][1]["alert"]["title"]


def test_delivery_failure_is_reported_without_leaking_the_secret_url(monkeypatch):
    def boom(url, body):
        raise RuntimeError(f"не удалось открыть {url}")

    monkeypatch.setattr(notify, "send_webhook", boom)
    result = notify.deliver(
        {"webhook_url": "http://gw.local/hook?key=SECRET"}, {"text": "x"}
    )
    assert "SECRET" not in result["webhook"] and "<webhook>" in result["webhook"]


def test_email_is_sent_through_smtp_settings(monkeypatch):
    mails = []
    monkeypatch.setattr(
        notify, "send_email", lambda cfg, subject, body: mails.append((cfg, subject))
    )
    cfg = {
        "email_to": "admin@local",
        "smtp_host": "mail.local",
        "smtp_port": 25,
        "smtp_from": "arm112@local",
        "smtp_tls": False,
    }
    assert notify.deliver(cfg, {"text": "заголовок\nтекст"}) == {"email": "ok"}
    assert mails[0][0]["host"] == "mail.local" and mails[0][1] == "заголовок"


def test_maybe_notify_respects_switch_and_marks_alert(monkeypatch):
    spawned = []
    base = {
        "enabled": True,
        "min_severity": "warning",
        "throttle_min": 15,
        "webhook_url": "http://gw.local/hook",
        "email_to": "",
        "smtp_host": "",
        "smtp_port": 25,
        "smtp_from": "a@b",
        "smtp_tls": False,
    }
    monkeypatch.setattr(notify, "_spawn", lambda cfg, payload: spawned.append(payload))

    monkeypatch.setattr(notify, "load_config", lambda: {**base, "enabled": False})
    assert notify.maybe_notify(alert()) is False

    monkeypatch.setattr(notify, "load_config", lambda: base)
    first = alert()
    assert notify.maybe_notify(first) is True and "notified_at" in first.details
    assert notify.maybe_notify(first) is False  # повтор в пределах окна
    assert len(spawned) == 1

    monkeypatch.setattr(notify, "load_config", lambda: {**base, "webhook_url": ""})
    assert notify.maybe_notify(alert()) is False  # каналов нет


def test_broken_settings_never_raise(monkeypatch):
    def boom():
        raise RuntimeError("нет БД")

    monkeypatch.setattr(notify, "load_config", boom)
    assert notify.maybe_notify(alert()) is False
