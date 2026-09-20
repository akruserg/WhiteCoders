"""ИИ-модуль на локальной модели YandexGPT-5-Lite-8B-instruct (GGUF).

Модель запускается сервером llama.cpp внутри контура (сервис llm в
docker-compose, профиль ai) и не ходит во внешние сети. Общение идет по
OpenAI-совместимому API /v1/chat/completions, структура ответа задается
JSON-схемой, поэтому модель не может вернуть произвольный текст вместо данных.

Если модуль выключен или недоступен, генерация сценариев отвечает 503, а
инсайты и рекомендации строятся правилами по статистике ошибок.
"""

import json
import re
from collections import Counter

import httpx
from flask import current_app

from ..core.errors import ApiError
from . import card_schema, settings

RULES_MODEL = "rules-v1"

_KIND_ADVICE = {
    "missing": "Отработать обязательные поля карточки: не оставлять их пустыми.",
    "content": "Уточнять у заявителя детали и переносить их в карточку без искажений.",
    "procedure": "Повторить порядок действий с карточкой по регламенту.",
    "timing": "Потренировать заполнение на скорость: норматив времени превышается.",
    "grammar": "Вычитывать текст перед сохранением: пробелы, регистр, знаки препинания.",
}
_KIND_TITLE = {
    "missing": "пропуски обязательных полей",
    "content": "расхождения с эталоном",
    "procedure": "нарушение порядка действий",
    "timing": "превышение времени",
    "grammar": "ошибки оформления текста",
}

_DIFFICULTY = {
    1: "простая: один очевидный факт, спокойный заявитель",
    2: "лёгкая: заявитель отвечает на вопросы по делу",
    3: "средняя: заявитель взволнован, часть данных нужно уточнять",
    4: "сложная: сбивчивая речь, противоречия, несколько пострадавших",
    5: "очень сложная: паника, неполные данные, несколько служб",
}


class AiUnavailable(ApiError):
    """Модель выключена, недоступна или вернула непригодный ответ."""

    def __init__(self, message="ИИ-модуль недоступен", details=None):
        super().__init__(message, 503, code="ai_unavailable", details=details)


# ------------------------------------------------------------------ состояние


def is_enabled():
    return bool(settings.get("ai.enabled", current_app.config["AI_ENABLED"]))


def scoring_enabled():
    default = current_app.config["AI_SCORING_ENABLED"]
    return is_enabled() and bool(settings.get("ai.scoring_enabled", default))


def model_name():
    return current_app.config["AI_MODEL_NAME"] if is_enabled() else "disabled"


def _client(timeout=None):
    cfg = current_app.config
    return httpx.Client(
        base_url=cfg["AI_BASE_URL"], timeout=timeout or cfg["AI_TIMEOUT_SEC"]
    )


def health():
    """Состояние llama.cpp-сервера для панели администратора."""
    if not is_enabled():
        return {"available": False, "reason": "disabled"}
    try:
        with _client(timeout=5) as client:
            response = client.get("/health")
        ok = response.status_code == 200
        return {"available": ok, "model": current_app.config["AI_MODEL_NAME"]}
    except httpx.HTTPError as exc:
        return {"available": False, "error": str(exc)}


# ------------------------------------------------------------------ обращение к модели


def _extract_json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                pass
    raise AiUnavailable("Модель вернула ответ не в формате JSON")


def _chat(system, user, schema, max_tokens=None, temperature=None, timeout=None):
    """Один запрос к модели. Возвращает разобранный JSON, соответствующий schema."""
    if not is_enabled():
        raise AiUnavailable("Модуль ИИ отключен")
    cfg = current_app.config
    payload = {
        "model": cfg["AI_MODEL_NAME"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": cfg["AI_TEMPERATURE"] if temperature is None else temperature,
        "max_tokens": max_tokens or cfg["AI_MAX_TOKENS"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": True, "schema": schema},
        },
    }
    try:
        with _client(timeout) as client:
            response = client.post("/v1/chat/completions", json=payload)
    except httpx.HTTPError as exc:
        raise AiUnavailable(f"Сервер модели недоступен: {exc}") from exc
    if response.status_code >= 400:
        raise AiUnavailable(
            f"Сервер модели ответил {response.status_code}",
            {"body": response.text[:300]},
        )
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise AiUnavailable("Неожиданный ответ сервера модели") from exc
    return _extract_json(content)


# ------------------------------------------------------------------ генерация сценариев

_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}

SYSTEM_METHODIST = (
    "Ты методист учебного центра ГБУ «Система 112» города Москвы. Готовишь учебные "
    "сценарии для тренажёра оператора дежурно-диспетчерской службы. Пишешь по-русски, "
    "реалистично, без реальных имён, адресов и телефонов конкретных людей: используй "
    "вымышленные данные и номера в формате +7495XXXXXXX."
)


def _scenario_schema(field_keys):
    card = {
        "type": "object",
        "properties": {key: _STR for key in field_keys},
        "required": list(field_keys),
    }
    return {
        "type": "object",
        "properties": {
            "title": _STR,
            "legend": {
                "type": "object",
                "properties": {
                    "summary": _STR,
                    "dialog": _STR_LIST,
                    "followups": _STR_LIST,
                    "hints": _STR_LIST,
                },
                "required": ["summary", "dialog", "followups", "hints"],
            },
            "reference_card": card,
            "reference_actions": {
                "type": "array",
                "items": {"type": "string", "enum": card_schema.ACTION_TYPES},
            },
        },
        "required": ["title", "legend", "reference_card", "reference_actions"],
    }


def _scenario_prompt(category, difficulty, fields, hints):
    listing = "\n".join(f"- {f['key']}: {f['label']}" for f in fields)
    extra = f"\nПожелания преподавателя: {hints}" if hints else ""
    return (
        f"Составь один учебный сценарий вызова по теме «{category.name}» "
        f"(код {category.code}). Сложность {difficulty} из 5: {_DIFFICULTY[difficulty]}.\n\n"
        "Поля legend:\n"
        "- summary: 1-2 предложения, что произошло;\n"
        "- dialog: 2-4 реплики заявителя (то, что он говорит, когда оператор снял трубку);\n"
        "- followups: ответы заявителя на типовые вопросы оператора по порядку "
        "(адрес, угроза людям, пострадавшие, детали), 3-5 реплик;\n"
        "- hints: 2-3 подсказки преподавателю, на что обратить внимание.\n\n"
        f"reference_card - эталонная карточка, значения по полям:\n{listing}\n"
        "Значения краткие, как их вносит оператор; недоступные по легенде поля - пустая строка. "
        "В поле services перечисли через запятую службы (Служба 101, Служба 103, "
        "Служба 104, Служба 102 и т.п.).\n"
        "reference_actions - порядок действий оператора с карточкой из допустимого списка."
        f"{extra}"
    )


def _clean_text(value, limit=500):
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value or "").strip()[:limit]


def _clean_lines(values, limit=6):
    lines = [_clean_text(v, 400) for v in (values or [])]
    return [line for line in lines if line][:limit]


def _draft(raw, category, difficulty, fields, time_limit_sec):
    keys = [f["key"] for f in fields]
    legend = raw.get("legend") or {}
    dialog = _clean_lines(legend.get("dialog"))
    if not dialog:
        return None
    card = {k: _clean_text((raw.get("reference_card") or {}).get(k)) for k in keys}
    actions = [
        a for a in raw.get("reference_actions") or [] if a in card_schema.ACTION_TYPES
    ]
    return {
        "title": _clean_text(raw.get("title"), 255) or f"{category.name}: сценарий",
        "category_id": category.id,
        "difficulty": difficulty,
        "legend": {
            "summary": _clean_text(legend.get("summary"), 600),
            "dialog": dialog,
            "followups": _clean_lines(legend.get("followups")),
            "hints": _clean_lines(legend.get("hints"), 4),
        },
        "reference_card": card,
        "reference_actions": actions or list(card_schema.DEFAULT_ACTIONS),
        "time_limit_sec": time_limit_sec,
        "ai_model": current_app.config["AI_MODEL_NAME"],
    }


def generate_scenarios(
    categories, count=5, difficulty=2, template_fields=None, time_limit_sec=30, hints=""
):
    """Черновики сценариев. По одному запросу на сценарий: надежнее на CPU."""
    fields = [
        f for f in (template_fields or []) if isinstance(f, dict) and f.get("key")
    ]
    if not fields or not categories:
        return []
    schema = _scenario_schema([f["key"] for f in fields])
    limit = current_app.config["AI_MAX_SCENARIOS_PER_REQUEST"]

    drafts, last_error = [], None
    for index in range(min(count, limit)):
        category = categories[index % len(categories)]
        try:
            raw = _chat(
                SYSTEM_METHODIST,
                _scenario_prompt(category, difficulty, fields, hints),
                schema,
            )
        except AiUnavailable as exc:
            last_error = exc
            if not drafts and index == 0:
                raise  # модель недоступна целиком: дальше пробовать нет смысла
            continue
        draft = _draft(raw, category, difficulty, fields, time_limit_sec)
        if draft:
            drafts.append(draft)
    if not drafts:
        raise last_error or AiUnavailable(
            "Модель не вернула ни одного пригодного сценария"
        )
    return drafts


# ------------------------------------------------------------------ коррекция по комментарию


def apply_correction(scenario, comment):
    """Правит сценарий по комментарию преподавателя. Возвращает (правка, пояснение)."""
    if not is_enabled():
        return {}, "Модуль ИИ отключен, комментарий сохранен без автоматической правки"

    keys = list((scenario.reference_card or {}).keys())
    schema = _scenario_schema(keys)
    schema = {
        "type": "object",
        "properties": {
            "explanation": _STR,
            "legend": schema["properties"]["legend"],
            "reference_card": schema["properties"]["reference_card"],
            "reference_actions": schema["properties"]["reference_actions"],
        },
        "required": ["explanation", "legend", "reference_card", "reference_actions"],
    }
    current = {
        "legend": scenario.legend,
        "reference_card": scenario.reference_card,
        "reference_actions": scenario.reference_actions,
    }
    user = (
        f"Текущий сценарий (JSON):\n{json.dumps(current, ensure_ascii=False)}\n\n"
        f"Комментарий преподавателя: {comment}\n\n"
        "Внеси в сценарий только то, что просит комментарий, остальное оставь как есть. "
        "Верни сценарий целиком и в explanation одним предложением опиши, что изменено."
    )
    try:
        raw = _chat(SYSTEM_METHODIST, user, schema)
    except AiUnavailable as exc:
        return {}, f"ИИ недоступен ({exc.message}), комментарий сохранен без правки"

    patch = {}
    legend = raw.get("legend") or {}
    new_legend = {
        "summary": _clean_text(legend.get("summary"), 600),
        "dialog": _clean_lines(legend.get("dialog")),
        "followups": _clean_lines(legend.get("followups")),
        "hints": _clean_lines(legend.get("hints"), 4),
    }
    if new_legend["dialog"] and new_legend != _strip_extra(scenario.legend, new_legend):
        # ключи вне схемы (например audio) сохраняем
        patch["legend"] = {**(scenario.legend or {}), **new_legend}
    card = {k: _clean_text((raw.get("reference_card") or {}).get(k)) for k in keys}
    if card != {k: _clean_text(v) for k, v in (scenario.reference_card or {}).items()}:
        patch["reference_card"] = card
    actions = [
        a for a in raw.get("reference_actions") or [] if a in card_schema.ACTION_TYPES
    ]
    if actions and actions != list(scenario.reference_actions or []):
        patch["reference_actions"] = actions
    return patch, _clean_text(raw.get("explanation"), 500) or "Сценарий обновлен"


def _strip_extra(legend, template):
    return {k: (legend or {}).get(k) for k in template}


# ------------------------------------------------------------------ инсайты и рекомендации


def _aggregate(error_rows):
    by_kind = Counter(kind for kind, _ in error_rows)
    by_field = Counter(field for _, field in error_rows if field)
    return {
        "by_kind": dict(by_kind.most_common()),
        "by_field": dict(by_field.most_common(10)),
        "total": sum(by_kind.values()),
    }


def _confidence(total):
    # чем больше наблюдений, тем увереннее вывод; порог 30 записей - «достаточно»
    return round(min(1.0, total / 30), 2)


def _rules_text(data, extra=""):
    if not data["total"]:
        return "Замечаний пока нет: данных для выводов недостаточно."
    lines = [f"Всего замечаний: {data['total']}."]
    for kind, count in list(data["by_kind"].items())[:3]:
        lines.append(
            f"- {_KIND_TITLE.get(kind, kind)}: {count}. {_KIND_ADVICE.get(kind, '')}"
        )
    if data["by_field"]:
        top = ", ".join(f"{k} ({v})" for k, v in list(data["by_field"].items())[:3])
        lines.append(f"Чаще всего ошибаются в полях: {top}.")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


_INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {"summary": _STR, "recommendations": _STR_LIST},
    "required": ["summary", "recommendations"],
}


def _llm_insight(subject, data, extra_facts):
    facts = json.dumps({**data, **extra_facts}, ensure_ascii=False)
    user = (
        f"{subject}\nДанные (JSON): {facts}\n"
        "Сформулируй краткий вывод (2-3 предложения) и 3-4 конкретные рекомендации "
        "по улучшению навыков. Виды замечаний: missing - пропуск обязательного поля, "
        "content - расхождение с эталоном, procedure - порядок действий, timing - время, "
        "grammar - оформление текста. Ничего не выдумывай сверх данных."
    )
    raw = _chat(SYSTEM_METHODIST, user, _INSIGHT_SCHEMA, max_tokens=700)
    tips = _clean_lines(raw.get("recommendations"), 5)
    text = _clean_text(raw.get("summary"), 800)
    return text + ("\n" + "\n".join(f"- {t}" for t in tips) if tips else "")


def _build(title, subject, data, extra_facts):
    body, model = None, RULES_MODEL
    if is_enabled() and data["total"]:
        try:
            body, model = _llm_insight(subject, data, extra_facts), model_name()
        except AiUnavailable:
            body = None  # модель не отвечает: остаются правила
    return {
        "title": title,
        "body": body or _rules_text(data),
        "data": data,
        "confidence": _confidence(data["total"]),
        "ai_model": model if body else RULES_MODEL,
    }


def build_group_insight(error_rows, group_name=None):
    title = (
        f"Типичные ошибки группы {group_name}"
        if group_name
        else "Типичные ошибки группы"
    )
    data = _aggregate(error_rows)
    return _build(
        title, "Проанализируй типичные ошибки учебной группы операторов.", data, {}
    )


def build_student_recommendation(stats, error_rows, full_name=None):
    title = f"Рекомендации: {full_name}" if full_name else "Рекомендации по подготовке"
    data = _aggregate(error_rows)
    data["stats"] = stats or {}
    # имя обучающегося в модель не передаем: персональные данные остаются в БД
    return _build(
        title, "Составь рекомендации для одного обучающегося оператора.", data, {}
    )


# ------------------------------------------------------------------ смысловая проверка


_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"equivalent": {"type": "boolean"}},
    "required": ["equivalent"],
}


def semantic_equal(label, expected, actual):
    """True/False - модель сравнила ответ с эталоном по смыслу, None - не смогла."""
    if not scoring_enabled():
        return None
    user = (
        f"Поле карточки: «{label}».\nЭталон: {expected}\nОтвет оператора: {actual}\n"
        "Передает ли ответ оператора тот же смысл и все существенные факты эталона "
        "(числа, адреса, названия должны совпадать)? Ответь JSON."
    )
    try:
        raw = _chat(
            "Ты строгий проверяющий работы операторов службы 112.",
            user,
            _JUDGE_SCHEMA,
            max_tokens=20,
            temperature=0,
            timeout=current_app.config["AI_JUDGE_TIMEOUT_SEC"],
        )
    except AiUnavailable:
        return None
    return bool(raw.get("equivalent"))
