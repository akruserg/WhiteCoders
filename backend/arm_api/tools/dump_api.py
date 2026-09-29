"""Собирает api.txt (контракт API) из маршрутов приложения.

    cd backend/arm_api && SECRET_KEY=x DATABASE_URL=postgresql://u:p@h/db CORS_ORIGINS=* \
        PYTHONPATH=src python tools/dump_api.py > ../../api.txt
"""

import re
import sys

from arm_api import app
from arm_api.core.security import is_public_path

TITLES = {
    "auth": "Аутентификация",
    "users": "Пользователи, роли, группы",
    "catalog": "Справочники: категории, шаблоны карточки, профили оценивания",
    "scenarios": "Учебные сценарии",
    "materials": "Методические материалы",
    "sessions": "Занятия, карточки, звонки",
    "results": "Прогресс и аналитика",
    "reports": "Отчеты, инсайты, сертификаты",
    "system": "Администрирование",
    "updates": "Пакетное обновление контента и настроек",
    "workstations": "Рабочие места (АРМ) и XML-конфигурации",
    "internal": "Служебные (arm_voip)",
    "meta": "Служебные",
}


def main():
    prefix = app.config["API_PREFIX"]
    groups = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        blueprint = rule.endpoint.split(".")[0]
        path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            auth = "без токена" if is_public_path(rule.rule, prefix) else "Bearer JWT"
            groups.setdefault(blueprint, []).append((path, method, auth))

    out = [
        "API-контракт АРМ-112 (учебное ПО подготовки операторов ДДС)",
        f"Базовый префикс: {prefix}. Формат: JSON, ошибки: "
        '{"error": {"code", "message", "details"}, "request_id"}.',
        "Авторизация: заголовок Authorization: Bearer <access_token>, получение: POST /auth/login.",
        f"Полная спецификация OpenAPI 3.1: GET {prefix}/openapi.json",
        f"Всего маршрутов: {sum(len(v) for v in groups.values())}",
        "",
    ]
    for blueprint in TITLES:
        rows = sorted(groups.get(blueprint, []))
        if not rows:
            continue
        out.append(f"== {TITLES[blueprint]} ==")
        width = max(len(p) for p, _, _ in rows)
        out += [f"{m:<7} {p:<{width}}  [{a}]" for p, m, a in rows]
        out.append("")
    sys.stdout.write("\n".join(out))


if __name__ == "__main__":
    main()
