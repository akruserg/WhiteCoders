"""
POST /reports                  - сформировать отчет (json/csv/xlsx/pdf)
GET  /reports                  - список сформированных отчетов
GET  /reports/{id}             - статус и метаданные
GET  /reports/{id}/download    - выгрузка файла
GET  /reports/formats          - какие форматы доступны в сборке

POST /insights/generate        - инсайты по типичным ошибкам / рекомендации
GET  /insights                 - список инсайтов
POST /insights/{id}/publish    - публикация обучающемуся

POST /certificates             - выдача сертификата по итогам занятия
GET  /certificates             - список сертификатов
"""

import os
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, request, send_file
from sqlalchemy import select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import current_user, is_admin, is_student, require, write_audit
from ..models import (
    Attempt,
    AttemptError,
    Certificate,
    Group,
    Insight,
    InsightKind,
    Report,
    ReportKind,
    ReportStatus,
    TrainingSession,
    User,
)
from ..schemas import CertificateIn, InsightGenerateIn, ReportCreateIn
from ..services import ai, analytics, reporting
from ._helpers import body, commit, get_or_404, item, ok

reports_bp = Blueprint("reports", __name__)


@reports_bp.get("/reports/formats")
def report_formats():
    current_user()
    return ok({"formats": reporting.available_formats()})


@reports_bp.post("/reports")
def create_report():
    principal = require("report.create", "report.read.any")
    payload = body(ReportCreateIn)

    if payload.format not in reporting.available_formats():
        raise ApiError(
            f"Формат {payload.format} недоступен в текущей сборке",
            501,
            code="format_unavailable",
            details={"available": reporting.available_formats()},
        )

    report = Report(
        kind=ReportKind(payload.kind),
        format=payload.format,
        session_id=payload.session_id,
        params=payload.params,
        status=ReportStatus.PROCESSING,
        created_by=principal.id,
    )
    db.session.add(report)
    db.session.flush()

    started = datetime.now(timezone.utc)
    try:
        title, data, rows = reporting.build(
            report.kind, session_id=report.session_id, params=report.params
        )
        report.file_path = reporting.render(
            report.format,
            title,
            data,
            rows,
            current_app.config["REPORTS_DIR"],
            f"report_{report.id}",
        )
        report.status = ReportStatus.READY
        report.ready_at = datetime.now(timezone.utc)
    except (ValueError, RuntimeError) as exc:
        report.status = ReportStatus.FAILED
        report.error = str(exc)
        write_audit(
            db.session,
            request,
            principal,
            "report.failed",
            "report",
            report.id,
            {"error": str(exc)},
        )
        commit()
        raise ApiError(f"Не удалось сформировать отчет: {exc}", 422)

    elapsed = (report.ready_at - started).total_seconds()
    write_audit(
        db.session,
        request,
        principal,
        "report.create",
        "report",
        report.id,
        {
            "kind": report.kind.value,
            "format": report.format,
            "elapsed_sec": round(elapsed, 2),
        },
    )
    commit()
    return ok(
        {
            **report.to_dict(),
            "elapsed_sec": round(elapsed, 2),
            "preview": data if report.format == "json" else None,
        },
        201,
    )


@reports_bp.get("/reports")
def list_reports():
    principal = require("report.create", "report.read.any")
    stmt = select(Report).order_by(Report.created_at.desc())
    if not is_admin(principal):
        stmt = stmt.where(Report.created_by == principal.id)
    if request.args.get("kind"):
        try:
            stmt = stmt.where(Report.kind == ReportKind(request.args["kind"]))
        except ValueError:
            raise ApiError("Некорректный kind", 422)
    if request.args.get("session_id"):
        stmt = stmt.where(Report.session_id == request.args["session_id"])
    return ok(paginate(stmt))


@reports_bp.get("/reports/<uuid:report_id>")
def get_report(report_id):
    principal = require("report.create", "report.read.any")
    report = get_or_404(Report, report_id, "Отчет")
    if not is_admin(principal) and report.created_by != principal.id:
        raise ApiError("Отчет другого пользователя", 403)
    return item(report)


@reports_bp.get("/reports/<uuid:report_id>/download")
def download_report(report_id):
    principal = require("report.create", "report.read.any")
    report = get_or_404(Report, report_id, "Отчет")
    if not is_admin(principal) and report.created_by != principal.id:
        raise ApiError("Отчет другого пользователя", 403)
    if report.status is not ReportStatus.READY or not report.file_path:
        raise ApiError("Отчет еще не готов", 409)
    if not os.path.exists(report.file_path):
        raise ApiError("Файл отчета отсутствует на диске", 404)

    mimetypes = {
        "json": "application/json",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    }
    return send_file(
        report.file_path,
        mimetype=mimetypes.get(report.format, "application/octet-stream"),
        as_attachment=True,
        download_name=f"{report.kind.value}_{report.created_at:%Y%m%d_%H%M}.{report.format}",
    )


@reports_bp.get("/sessions/<uuid:session_id>/report")
def session_report(session_id):
    principal = require("session.manage", "report.read.any")
    session = get_or_404(TrainingSession, session_id, "Занятие")
    if not is_admin(principal) and session.teacher_id != principal.id:
        raise ApiError("Занятие другого преподавателя", 403)
    title, data, rows = reporting.build(ReportKind.SESSION, session_id=session.id)
    return ok({"title": title, "data": data, "table": rows})


@reports_bp.post("/insights/generate")
def generate_insight():
    principal = require("insight.manage")
    payload = body(InsightGenerateIn)
    kind = InsightKind(payload.kind)

    where = []
    if payload.session_id:
        where.append(Attempt.session_id == payload.session_id)
    if payload.target_user_id:
        where.append(Attempt.user_id == payload.target_user_id)
    if payload.target_group_id:
        group = get_or_404(Group, payload.target_group_id, "Группа")
        member_ids = [m.id for m in group.members] or [None]
        where.append(Attempt.user_id.in_(member_ids))
    if not where:
        raise ApiError("Укажите занятие, обучающегося или группу", 422)

    error_rows = db.session.execute(
        select(AttemptError.kind, AttemptError.field_key)
        .join(Attempt, Attempt.id == AttemptError.attempt_id)
        .where(*where)
        .limit(10000)
    ).all()
    error_rows = [(kind_.value, field) for kind_, field in error_rows]

    if kind is InsightKind.STUDENT_RECOMMENDATION:
        if not payload.target_user_id:
            raise ApiError("Для рекомендаций нужен target_user_id", 422)
        user = get_or_404(User, payload.target_user_id, "Пользователь")
        stats = analytics.user_progress(user.id)["summary"]
        built = ai.build_student_recommendation(stats, error_rows, user.full_name)
    else:
        group_name = None
        if payload.target_group_id:
            group_name = db.session.get(Group, payload.target_group_id).name
        built = ai.build_group_insight(error_rows, group_name)
        if kind is InsightKind.SESSION_SUMMARY and payload.session_id:
            built["data"]["session"] = analytics.session_results(payload.session_id)

    insight = Insight(
        kind=kind,
        session_id=payload.session_id,
        target_user_id=payload.target_user_id,
        target_group_id=payload.target_group_id,
        is_published=payload.publish,
        **built,
    )
    db.session.add(insight)
    db.session.flush()
    write_audit(
        db.session,
        request,
        principal,
        "insight.generate",
        "insight",
        insight.id,
        {"kind": kind.value},
    )
    commit()
    return item(insight, 201)


@reports_bp.get("/insights")
def list_insights():
    principal = current_user()
    stmt = select(Insight).order_by(Insight.created_at.desc())
    if is_student(principal):
        stmt = stmt.where(
            Insight.target_user_id == principal.id, Insight.is_published.is_(True)
        )
    if request.args.get("session_id"):
        stmt = stmt.where(Insight.session_id == request.args["session_id"])
    if request.args.get("kind"):
        try:
            stmt = stmt.where(Insight.kind == InsightKind(request.args["kind"]))
        except ValueError:
            raise ApiError("Некорректный kind", 422)
    return ok(paginate(stmt))


@reports_bp.post("/insights/<uuid:insight_id>/publish")
def publish_insight(insight_id):
    principal = require("insight.manage")
    insight = get_or_404(Insight, insight_id, "Инсайт")
    insight.is_published = True
    write_audit(
        db.session, request, principal, "insight.publish", "insight", insight.id
    )
    commit()
    return item(insight)


@reports_bp.post("/certificates")
def issue_certificate():
    principal = require("certificate.issue")
    payload = body(CertificateIn)
    user = get_or_404(User, payload.user_id, "Пользователь")

    progress = analytics.user_progress(user.id, payload.session_id)
    score = progress["summary"]["avg_score"]
    if not progress["summary"]["attempts"]:
        raise ApiError("У обучающегося нет оцененных карточек", 409)

    number = (
        f"АРМ112-{datetime.now(timezone.utc):%Y}-{uuid_mod.uuid4().hex[:8].upper()}"
    )
    certificate = Certificate(
        number=number,
        user_id=user.id,
        session_id=payload.session_id,
        issued_by=principal.id,
        score=score,
        valid_until=datetime.now(timezone.utc)
        + timedelta(days=30 * payload.valid_months),
        payload={"summary": progress["summary"], "full_name": user.full_name},
    )
    db.session.add(certificate)
    db.session.flush()
    write_audit(
        db.session,
        request,
        principal,
        "certificate.issue",
        "certificate",
        certificate.id,
        {"user_id": str(user.id), "score": score},
    )
    commit()
    return item(certificate, 201)


@reports_bp.get("/certificates")
def list_certificates():
    principal = current_user()
    stmt = select(Certificate).order_by(Certificate.issued_at.desc())
    if is_student(principal):
        stmt = stmt.where(Certificate.user_id == principal.id)
    elif request.args.get("user_id"):
        stmt = stmt.where(Certificate.user_id == request.args["user_id"])
    return ok(paginate(stmt))
