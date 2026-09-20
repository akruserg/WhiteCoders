import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..core.extensions import db
from ..models import (
    Attempt,
    AttemptError,
    AuditLog,
    Group,
    ReportKind,
    Scenario,
    TrainingSession,
    User,
)
from . import analytics

SUPPORTED_FORMATS = ("json", "csv", "xlsx", "pdf")


def _xlsx_available():
    try:
        return True
    except ImportError:
        return False


def _pdf_available():
    try:
        return True
    except ImportError:
        return False


def available_formats():
    formats = ["json", "csv"]
    if _xlsx_available():
        formats.append("xlsx")
    if _pdf_available():
        formats.append("pdf")
    return formats


def build(kind, session_id=None, params=None):
    params = params or {}
    kind = ReportKind(kind) if not isinstance(kind, ReportKind) else kind

    if kind is ReportKind.SESSION:
        return _session_report(session_id)
    if kind is ReportKind.STUDENT_PROGRESS:
        return _student_report(params.get("user_id"), session_id)
    if kind is ReportKind.GROUP_PROGRESS:
        return _group_report(params.get("group_id"))
    if kind is ReportKind.ERROR_HEATMAP:
        data = analytics.error_heatmap(
            session_id=session_id,
            group_id=params.get("group_id"),
            category_id=params.get("category_id"),
        )
        rows = [["Поле карточки", "Вид замечания", "Количество"]]
        rows += [[c["field_key"], c["kind"], c["count"]] for c in data["cells"]]
        return "Тепловая карта ошибок", data, rows
    if kind is ReportKind.SYSTEM_USAGE:
        data = analytics.system_usage()
        rows = [["Показатель", "Значение"]] + [
            [k, json.dumps(v, ensure_ascii=False)] for k, v in data.items()
        ]
        return "Использование системы", data, rows
    if kind is ReportKind.SECURITY_AUDIT:
        return _audit_report(params)
    raise ValueError(f"Неизвестный вид отчета: {kind}")


def _session_report(session_id):
    session = db.session.get(TrainingSession, session_id)
    if session is None:
        raise ValueError("Занятие не найдено")

    results = analytics.session_results(session.id)
    attempts = list(
        db.session.execute(
            select(Attempt)
            .where(Attempt.session_id == session.id)
            .order_by(Attempt.user_id, Attempt.seq)
        ).scalars()
    )

    details = []
    for attempt in attempts:
        scenario = db.session.get(Scenario, attempt.scenario_id)
        user = db.session.get(User, attempt.user_id)
        errors = list(
            db.session.execute(
                select(AttemptError).where(AttemptError.attempt_id == attempt.id)
            ).scalars()
        )
        details.append(
            {
                "attempt_id": str(attempt.id),
                "user": user.full_name if user else None,
                "seq": attempt.seq,
                "scenario": scenario.title if scenario else None,
                "score": attempt.final_score,
                "passed": attempt.passed,
                "duration_sec": round((attempt.duration_ms or 0) / 1000, 1),
                "time_limit_sec": attempt.time_limit_sec,
                "delta_sec": round((attempt.time_overrun_ms or 0) / 1000, 1),
                "grammar_errors": sum(1 for e in errors if e.kind.value == "grammar"),
                "errors": [e.to_dict() for e in errors],
                "expert_comment": attempt.expert_comment,
            }
        )

    data = {
        "session": session.to_dict(),
        "results": results,
        "attempts": details,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    rows = [
        [
            "Обучающийся",
            "№",
            "Сценарий",
            "Балл",
            "Зачет",
            "Время, с",
            "Норматив, с",
            "Отклонение, с",
            "Замечаний",
            "Из них грамматика",
        ]
    ]
    for item in details:
        rows.append(
            [
                item["user"],
                item["seq"],
                item["scenario"],
                item["score"],
                "да" if item["passed"] else "нет",
                item["duration_sec"],
                item["time_limit_sec"],
                item["delta_sec"],
                len(item["errors"]),
                item["grammar_errors"],
            ]
        )
    return f"Отчет о практическом занятии: {session.title}", data, rows


def _student_report(user_id, session_id=None):
    user = db.session.get(User, user_id) if user_id else None
    if user is None:
        raise ValueError("Обучающийся не найден")
    data = analytics.user_progress(user.id, session_id)
    data["user"] = {
        "id": str(user.id),
        "full_name": user.full_name,
        "username": user.username,
    }
    rows = [["Занятие", "Дата", "Карточек", "Средний балл"]]
    rows += [
        [i["title"], i["started_at"], i["attempts"], i["avg_score"]]
        for i in data["timeline"]
    ]
    return f"Прогресс обучающегося: {user.full_name}", data, rows


def _group_report(group_id):
    group = db.session.get(Group, group_id) if group_id else None
    if group is None:
        raise ValueError("Группа не найдена")
    students = []
    for member in group.members:
        progress = analytics.user_progress(member.id)
        students.append(
            {
                "user_id": str(member.id),
                "full_name": member.full_name,
                **progress["summary"],
            }
        )
    data = {
        "group": group.to_dict(),
        "students": students,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    rows = [
        ["Обучающийся", "Карточек", "Средний балл", "Зачетов", "Превышений норматива"]
    ]
    rows += [
        [s["full_name"], s["attempts"], s["avg_score"], s["passed"], s["time_overruns"]]
        for s in students
    ]
    return f"Прогресс группы: {group.name}", data, rows


def _audit_report(params):
    days = int(params.get("days", 30))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    entries = list(
        db.session.execute(
            select(AuditLog)
            .where(AuditLog.ts >= since)
            .order_by(AuditLog.ts.desc())
            .limit(5000)
        ).scalars()
    )
    data = {"since": since.isoformat(), "entries": [e.to_dict() for e in entries]}
    rows = [["Время", "Пользователь", "Роль", "Действие", "Объект", "IP"]]
    rows += [
        [
            e.ts.isoformat(),
            str(e.user_id or ""),
            e.role_code or "",
            e.action,
            f"{e.object_type or ''}:{e.object_id or ''}",
            e.ip or "",
        ]
        for e in entries
    ]
    return f"Аудит безопасности за {days} дн.", data, rows


def render(fmt, title, data, rows, target_dir, filename):
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{filename}.{fmt}")

    if fmt == "json":
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"title": title, "data": data}, fh, ensure_ascii=False, indent=2)
        return path

    if fmt == "csv":
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow([title])
            writer.writerows(rows)
        return path

    if fmt == "xlsx":
        if not _xlsx_available():
            raise RuntimeError("Формат xlsx недоступен: не установлен openpyxl")
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Отчет"
        sheet.append([title])
        for row in rows:
            sheet.append(list(row))
        workbook.save(path)
        return path

    if fmt == "pdf":
        if not _pdf_available():
            raise RuntimeError("Формат pdf недоступен: не установлен reportlab")
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors

        doc = SimpleDocTemplate(path, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        table = Table([[str(cell) for cell in row] for row in rows], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                ]
            )
        )
        doc.build([Paragraph(title, styles["Title"]), table])
        return path

    raise RuntimeError(f"Неподдерживаемый формат: {fmt}")


def to_csv_bytes(title, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([title])
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")
