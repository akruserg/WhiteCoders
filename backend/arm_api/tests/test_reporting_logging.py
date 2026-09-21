import json
import logging
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from arm_api.core.logging import JsonFormatter
from arm_api.core.security import ADMIN_REPORT_KINDS, ROLE_PERMISSIONS
from arm_api.services import reporting


def has_font():
    try:
        reporting._pdf_fonts()
        return True
    except RuntimeError:
        return False


needs_font = pytest.mark.skipif(not has_font(), reason="нет шрифта с кириллицей")


def test_available_formats_reflect_real_libraries():
    assert {"json", "csv"} <= set(reporting.available_formats())
    assert reporting._xlsx_available() is True  # библиотеки в окружении установлены


@needs_font
def test_pdf_report_with_cyrillic_is_created(tmp_path):
    path = reporting.render(
        "pdf",
        "Отчёт по занятию",
        {},
        [["Обучающийся", "Балл"], ["Петрова А.", "91"]],
        str(tmp_path),
        "r",
    )
    assert os.path.getsize(path) > 1000 and open(path, "rb").read(4) == b"%PDF"


@needs_font
def test_certificate_pdf_is_created(tmp_path):
    cert = SimpleNamespace(
        id="c1",
        number="АРМ112-2026-AAAA1111",
        score=88.5,
        issued_at=datetime.now(timezone.utc),
        valid_until=None,
        payload={
            "full_name": "Петрова Анна",
            "summary": {"attempts": 5, "pass_rate": 80},
        },
    )
    path = reporting.render_certificate(cert, str(tmp_path))
    assert path.endswith(".pdf") and os.path.getsize(path) > 1000


def test_json_log_line_is_valid_and_keeps_cyrillic():
    record = logging.LogRecord(
        "arm_api", logging.WARNING, __file__, 1, "Занятие %s завершено", ("А-1",), None
    )
    line = JsonFormatter().format(record)
    data = json.loads(line)
    assert data["message"] == "Занятие А-1 завершено" and data["level"] == "WARNING"
    assert "Занятие" in line  # не экранируется в \uXXXX


def test_admin_has_no_access_to_student_results_only_system_reports():
    admin = set(ROLE_PERMISSIONS["admin"])
    assert "report.read.any" not in admin and "attempt.grade" not in admin
    assert {"system.manage", "audit.read", "user.manage"} <= admin
    assert ADMIN_REPORT_KINDS == {"system_usage", "security_audit"}
    assert "report.read.any" in ROLE_PERMISSIONS["teacher"]


def test_httpx_requests_are_not_logged_so_webhook_keys_stay_out_of_logs():
    import logging

    from arm_api.core.logging import setup_logging

    setup_logging("text", logging.INFO)
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
