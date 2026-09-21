import json
import logging
import sys
from datetime import datetime, timezone

from flask import g, has_request_context


class JsonFormatter(logging.Formatter):
    """Одна строка JSON на запись журнала (требование ТЗ к формату логов)."""

    def format(self, record):
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if has_request_context() and getattr(g, "request_id", None):
            entry["request_id"] = g.request_id
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(fmt="json", level=logging.INFO):
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # httpx в INFO пишет полный адрес запроса, а в адресе webhook оповещений может быть
    # ключ доступа: без этого он попадал бы в журнал
    numeric = (
        level if isinstance(level, int) else logging.getLevelName(str(level).upper())
    )
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(
            max(numeric if isinstance(numeric, int) else logging.INFO, logging.WARNING)
        )
