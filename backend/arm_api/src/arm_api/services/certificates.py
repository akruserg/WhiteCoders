"""Выдача сертификата обучающемуся. Общая для ручной выдачи (POST /certificates)
и автоматической по итогам аттестации (services/attestation.py)."""

import os
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..core.errors import ApiError
from ..core.extensions import db
from ..models import Certificate
from . import analytics, reporting


def issue(user, session_id, issued_by_id, valid_months=12):
    """Создает сертификат по оцененным карточкам. Коммит - на вызывающем."""
    progress = analytics.user_progress(user.id, session_id)
    if not progress["summary"]["attempts"]:
        raise ApiError("У обучающегося нет оцененных карточек", 409)
    now = datetime.now(timezone.utc)
    certificate = Certificate(
        number=f"АРМ112-{now:%Y}-{uuid_mod.uuid4().hex[:8].upper()}",
        user_id=user.id,
        session_id=session_id,
        issued_by=issued_by_id,
        score=progress["summary"]["avg_score"],
        valid_until=now + timedelta(days=30 * valid_months),
        payload={"summary": progress["summary"], "full_name": user.full_name},
    )
    db.session.add(certificate)
    db.session.flush()
    try:
        certificate.file_path = reporting.render_certificate(
            certificate, os.path.join(current_app.config["REPORTS_DIR"], "certificates")
        )
    except (RuntimeError, OSError) as exc:  # сертификат выдан, файл можно собрать позже
        current_app.logger.warning(
            "PDF сертификата %s не создан: %s", certificate.number, exc
        )
    return certificate
