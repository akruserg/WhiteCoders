import csv
import io
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from sqlalchemy import func, select

from ..core.extensions import db
from ..models import (
    Alert,
    Attempt,
    AttemptError,
    AuditLog,
    Backup,
    Group,
    Report,
    ReportKind,
    ReportStatus,
    Scenario,
    SystemEvent,
    TrainingSession,
    User,
)
from . import analytics

SUPPORTED_FORMATS = ("json", "csv", "xlsx", "pdf")
# PDF с десятками тысяч строк верстается десятки секунд (ТЗ: отчет не более 30 с) и
# бесполезен для чтения: сверх лимита таблица сокращается, полные данные - в csv/xlsx
PDF_MAX_ROWS = 3000


def _xlsx_available():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return False
    return True


def _pdf_available():
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


# Стандартные шрифты PDF без кириллицы, поэтому нужен файл TTF. Путь можно
# задать переменной PDF_FONT_PATH, иначе ищем DejaVu (в образе ставится пакетом
# fonts-dejavu-core) и системные шрифты разработчика.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
_registered_fonts = {}


def _pdf_fonts():
    """Регистрирует шрифты (обычный, жирный) и возвращает их имена."""
    if _registered_fonts:
        return _registered_fonts["regular"], _registered_fonts["bold"]

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    paths = [os.environ.get("PDF_FONT_PATH", "")] + list(_FONT_CANDIDATES)
    regular = next((p for p in paths if p and os.path.exists(p)), None)
    if regular is None:
        raise RuntimeError(
            "Не найден шрифт с кириллицей для PDF: задайте PDF_FONT_PATH "
            "или установите fonts-dejavu-core"
        )
    bold = regular.replace("Sans.ttf", "Sans-Bold.ttf").replace(
        "arial.ttf", "arialbd.ttf"
    )
    pdfmetrics.registerFont(TTFont("AppFont", regular))
    pdfmetrics.registerFont(
        TTFont("AppFont-Bold", bold if os.path.exists(bold) else regular)
    )
    _registered_fonts.update(regular="AppFont", bold="AppFont-Bold")
    return "AppFont", "AppFont-Bold"


def available_formats():
    formats = ["json", "csv"]
    if _xlsx_available():
        formats.append("xlsx")
    if _pdf_available():
        formats.append("pdf")
    return formats


def _uuid(value, what="Идентификатор"):
    """UUID из params отчета (там строка). None остается None."""
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        raise ValueError(f"{what} должен быть UUID")


class Namer:
    """Подставляет вместо ФИО «Обучающийся N», если отчет нужно обезличить
    (params.anonymize = true). Нумерация одинакова внутри одного отчета."""

    def __init__(self, anonymize=False):
        self.anonymize = bool(anonymize)
        self._numbers = {}

    def name(self, user_id, full_name):
        if not self.anonymize:
            return full_name
        number = self._numbers.setdefault(str(user_id), len(self._numbers) + 1)
        return f"Обучающийся {number}"

    def login(self, user_id, username):
        return self.name(user_id, username) if self.anonymize else username


def build(kind, session_id=None, params=None):
    params = params or {}
    kind = ReportKind(kind) if not isinstance(kind, ReportKind) else kind
    namer = Namer(params.get("anonymize"))

    if kind is ReportKind.SESSION:
        return _session_report(session_id, namer)
    if kind is ReportKind.STUDENT_PROGRESS:
        return _student_report(
            _uuid(params.get("user_id"), "user_id"), session_id, namer
        )
    if kind is ReportKind.GROUP_PROGRESS:
        return _group_report(_uuid(params.get("group_id"), "group_id"), namer)
    if kind is ReportKind.ERROR_HEATMAP:
        data = analytics.error_heatmap(
            session_id=session_id,
            group_id=_uuid(params.get("group_id"), "group_id"),
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
    if kind is ReportKind.SYSTEM_ERRORS:
        return _errors_report(params)
    raise ValueError(f"Неизвестный вид отчета: {kind}")


def _session_report(session_id, namer):
    session = db.session.get(TrainingSession, session_id)
    if session is None:
        raise ValueError("Занятие не найдено")

    results = analytics.session_results(session.id)
    for student in results["students"]:
        student["full_name"] = namer.name(student["user_id"], student["full_name"])
    attempts = list(
        db.session.execute(
            select(Attempt)
            .where(Attempt.session_id == session.id)
            .order_by(Attempt.user_id, Attempt.seq)
        ).scalars()
    )

    # замечания всего занятия одним запросом: по запросу на карточку отчет по
    # 20 тысячам карточек строился десятки секунд (норма ТЗ: не более 30 с)
    errors_by_attempt = {}
    for error in db.session.execute(
        select(AttemptError)
        .join(Attempt, Attempt.id == AttemptError.attempt_id)
        .where(Attempt.session_id == session.id)
        .order_by(AttemptError.id)
    ).scalars():
        errors_by_attempt.setdefault(error.attempt_id, []).append(error)

    # названия и имена - двумя запросами, а не по запросу на карточку
    titles = dict(
        db.session.execute(
            select(Scenario.id, Scenario.title).where(
                Scenario.id.in_({a.scenario_id for a in attempts})
            )
        ).all()
    )
    names = dict(
        db.session.execute(
            select(User.id, User.full_name).where(
                User.id.in_({a.user_id for a in attempts})
            )
        ).all()
    )

    details = []
    for attempt in attempts:
        errors = errors_by_attempt.get(attempt.id, [])
        details.append(
            {
                "attempt_id": str(attempt.id),
                "user": (
                    namer.name(attempt.user_id, names[attempt.user_id])
                    if attempt.user_id in names
                    else None
                ),
                "seq": attempt.seq,
                "scenario": titles.get(attempt.scenario_id),
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
    title = f"Отчет о практическом занятии: {session.title}"
    exam = _attestation_block(session, namer)
    if exam:
        data["attestation"] = exam
        rows += attestation_rows(exam)
        title = f"Протокол аттестации: {session.title}"
    return title, data, rows


def attestation_rows(exam):
    """Строки протокола аттестации для таблицы отчета (без обращения к БД)."""
    cfg = exam["config"]
    rows = [
        [],
        [
            f"Протокол аттестации. Проходной балл: {cfg['pass_score']:g}, "
            f"минимум карточек: {cfg['min_attempts']}"
        ],
        ["Обучающийся", "Карточек", "Средний балл", "Результат", "Сертификат"],
    ]
    for s in exam["students"]:
        if not s["enough_attempts"]:
            result = "недостаточно карточек"
        else:
            result = "аттестован" if s["passed"] else "не аттестован"
        rows.append(
            [
                s["full_name"],
                s["attempts"],
                s["average"],
                result,
                s["certificate"] or "",
            ]
        )
    rows.append(["Итого аттестовано", f"{exam['passed']} из {exam['total']}"])
    return rows


def _attestation_block(session, namer):
    from . import attestation  # позже, чтобы не было циклического импорта

    if attestation.config(session) is None:
        return None
    exam = attestation.summarize(session)
    for student in exam["students"]:
        student["full_name"] = namer.name(student["user_id"], student["full_name"])
        if namer.anonymize:
            student["user_id"] = None
    return exam


def _student_report(user_id, session_id=None, namer=None):
    user = db.session.get(User, user_id) if user_id else None
    if user is None:
        raise ValueError("Обучающийся не найден")
    namer = namer or Namer()
    shown = namer.name(user.id, user.full_name)
    data = analytics.user_progress(user.id, session_id)
    data["user"] = {
        "id": str(user.id) if not namer.anonymize else None,
        "full_name": shown,
        "username": namer.login(user.id, user.username),
    }
    rows = [["Занятие", "Дата", "Карточек", "Средний балл"]]
    rows += [
        [i["title"], i["started_at"], i["attempts"], i["avg_score"]]
        for i in data["timeline"]
    ]
    return f"Прогресс обучающегося: {shown}", data, rows


def _group_report(group_id, namer=None):
    group = db.session.get(Group, group_id) if group_id else None
    if group is None:
        raise ValueError("Группа не найдена")
    namer = namer or Namer()
    students = []
    for member in group.members:
        progress = analytics.user_progress(member.id)
        students.append(
            {
                "user_id": str(member.id) if not namer.anonymize else None,
                "full_name": namer.name(member.id, member.full_name),
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


def errors_rows(data):
    """Таблица отчета об ошибках и сбоях из собранных данных (без обращения к БД)."""
    rows = [["Раздел", "Время", "Компонент / уровень", "Описание", "Подробности"]]
    for a in data["alerts"]:
        rows.append(
            [
                "Оповещение",
                a["first_seen_at"],
                f"{a['component']} / {a['severity']}",
                a["title"],
                f"повторов: {a['occurrences']}, статус: {a['status']}",
            ]
        )
    for e in data["events"]:
        rows.append(
            ["Событие", e["ts"], f"{e['component']} / {e['level']}", e["message"], ""]
        )
    for b in data["failed_backups"]:
        rows.append(
            [
                "Резервная копия",
                b["started_at"],
                "backup / failed",
                b["error"] or "",
                "",
            ]
        )
    for f in data["failed_reports"]:
        rows.append(
            ["Отчет", f["created_at"], f"reports / {f['kind']}", f["error"] or "", ""]
        )
    summary = data["summary"]
    rows.append(
        ["Итого", "", "", "", ", ".join(f"{k}: {v}" for k, v in summary.items())]
    )
    return rows


def _errors_report(params):
    """Отчет об ошибках и сбоях за период (ТЗ: отчеты администратора об ошибках и сбоях)."""
    days = min(max(int(params.get("days", 30)), 1), 365)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    limit = 2000
    alerts = list(
        db.session.execute(
            select(Alert)
            .where(Alert.last_seen_at >= since)
            .order_by(Alert.first_seen_at.desc())
            .limit(limit)
        ).scalars()
    )
    events = list(
        db.session.execute(
            select(SystemEvent)
            .where(
                SystemEvent.ts >= since, SystemEvent.level.in_(["error", "critical"])
            )
            .order_by(SystemEvent.ts.desc())
            .limit(limit)
        ).scalars()
    )
    backups = list(
        db.session.execute(
            select(Backup)
            .where(Backup.status == "failed", Backup.started_at >= since)
            .order_by(Backup.started_at.desc())
            .limit(limit)
        ).scalars()
    )
    reports = list(
        db.session.execute(
            select(Report)
            .where(Report.status == ReportStatus.FAILED, Report.created_at >= since)
            .order_by(Report.created_at.desc())
            .limit(limit)
        ).scalars()
    )
    failed_logins = db.session.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.ts >= since, AuditLog.action == "auth.login_failed")
    ).scalar_one()
    by_component = {}
    for a in alerts:
        by_component[a.component] = by_component.get(a.component, 0) + 1
    data = {
        "since": since.isoformat(),
        "days": days,
        "alerts": [a.to_dict() for a in alerts],
        "alerts_by_component": by_component,
        "events": [e.to_dict() for e in events],
        "failed_backups": [
            {"started_at": b.started_at.isoformat(), "error": b.error} for b in backups
        ],
        "failed_reports": [
            {
                "created_at": r.created_at.isoformat(),
                "kind": r.kind.value,
                "error": r.error,
            }
            for r in reports
        ],
        "summary": {
            "alerts": len(alerts),
            "critical_alerts": sum(1 for a in alerts if a.severity.value == "critical"),
            "error_events": len(events),
            "failed_backups": len(backups),
            "failed_reports": len(reports),
            "failed_logins": failed_logins,
        },
    }
    return f"Ошибки и сбои за {days} дн.", data, errors_rows(data)


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


def pdf_rows(rows, limit=PDF_MAX_ROWS):
    """Строки для PDF: (строки, сколько строк пропущено). Блоки после пустой строки
    (например, протокол аттестации) сохраняются целиком."""
    if len(rows) <= limit:
        return rows, 0
    tail_start = next((i for i, row in enumerate(rows) if i and not row), len(rows))
    tail = rows[tail_start:]
    head = rows[: max(limit - len(tail), 1)]
    return head + tail, max(tail_start - len(head), 0)


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
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

        regular, bold = _pdf_fonts()
        rows, omitted = pdf_rows(rows)
        cell_style = ParagraphStyle("cell", fontName=regular, fontSize=7, leading=9)
        title_style = ParagraphStyle("title", fontName=bold, fontSize=16, leading=20)
        doc = SimpleDocTemplate(path, pagesize=landscape(A4))
        # Paragraph переносит длинный текст внутри ячейки, а не режет его
        table = Table(
            [
                [Paragraph(escape(str(cell)), cell_style) for cell in row]
                for row in rows
            ],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story = [Paragraph(escape(title), title_style), table]
        if omitted:
            story.append(
                Paragraph(
                    f"Показана часть таблицы: пропущено строк {omitted}. "
                    "Полный перечень - в форматах csv, xlsx и json.",
                    cell_style,
                )
            )
        doc.build(story)
        return path

    raise RuntimeError(f"Неподдерживаемый формат: {fmt}")


def to_csv_bytes(title, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([title])
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def render_certificate(certificate, target_dir):
    """PDF-сертификат об итогах обучения. Возвращает путь к файлу."""
    if not _pdf_available():
        raise RuntimeError("Сертификат недоступен: не установлен reportlab")
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    regular, bold = _pdf_fonts()
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"certificate_{certificate.id}.pdf")
    width, height = landscape(A4)
    summary = (certificate.payload or {}).get("summary", {})
    full_name = (certificate.payload or {}).get("full_name", "")

    pdf = canvas.Canvas(path, pagesize=landscape(A4))
    pdf.setStrokeColor(colors.HexColor("#EC653B"))
    pdf.setLineWidth(3)
    pdf.rect(28, 28, width - 56, height - 56)

    def line(y, text, font, size, color="#1F2326"):
        pdf.setFont(font, size)
        pdf.setFillColor(colors.HexColor(color))
        pdf.drawCentredString(width / 2, y, text)

    line(height - 100, "СЕРТИФИКАТ", bold, 34, "#EC653B")
    line(height - 135, "об успешном прохождении обучения оператора ДДС", regular, 14)
    line(height - 200, "Настоящим подтверждается, что", regular, 13)
    line(height - 245, full_name, bold, 26)
    line(
        height - 285,
        "прошел(а) подготовку на тренажёре АРМ-112 ГБУ «Система 112»",
        regular,
        13,
    )
    line(
        height - 335,
        f"Средний балл: {float(certificate.score):.1f} из 100.  "
        f"Карточек оценено: {summary.get('attempts', 0)}.  "
        f"Доля зачёта: {summary.get('pass_rate', 0)}%",
        regular,
        13,
    )
    valid = (
        f"{certificate.valid_until:%d.%m.%Y}"
        if certificate.valid_until
        else "бессрочно"
    )
    line(
        90,
        f"Номер {certificate.number}  ·  выдан {certificate.issued_at:%d.%m.%Y}  ·  действителен до {valid}",
        regular,
        10,
        "#6B7378",
    )
    pdf.save()
    return path
