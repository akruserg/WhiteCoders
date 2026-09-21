from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..core.extensions import db
from ..models import Alert, AlertSeverity, AlertStatus
from . import notify


def raise_alert(component, title, fingerprint, severity="warning", details=None):
    """Открывает оповещение или увеличивает счетчик уже открытого.

    Пока предыдущее оповещение с тем же fingerprint не закрыто, новых не создаем.
    """
    now = datetime.now(timezone.utc)
    alert = (
        db.session.execute(
            select(Alert).where(
                Alert.fingerprint == fingerprint,
                Alert.status != AlertStatus.RESOLVED,
            )
        )
        .scalars()
        .first()
    )
    if alert is not None:
        alert.occurrences = (alert.occurrences or 1) + 1
        alert.last_seen_at = now
        # отметки служебных полей (например, notified_at) сохраняются
        alert.details = {**(alert.details or {}), **(details or {})}
        notify.maybe_notify(alert)
        return alert

    alert = Alert(
        component=component,
        severity=AlertSeverity(severity),
        title=title,
        fingerprint=fingerprint,
        details=details or {},
    )
    try:
        with db.session.begin_nested():
            db.session.add(alert)
    except IntegrityError:  # параллельный запрос успел открыть такое же
        return None
    notify.maybe_notify(alert)
    return alert
