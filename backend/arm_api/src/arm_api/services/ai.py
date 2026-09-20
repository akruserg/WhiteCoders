"""це вайбкод заглушка. уничтожить в последующих коммитах"""

MODEL_NAME = "disabled"


def generate_scenarios(
    categories, count=5, difficulty=2, template_fields=None, time_limit_sec=30, hints=""
):
    return []


def apply_correction(scenario, comment):
    return {}, "Модуль ИИ отключен, комментарий сохранен без автоматической правки"


def build_group_insight(error_rows, group_name=None):
    title = (
        f"Типичные ошибки группы {group_name}"
        if group_name
        else "Типичные ошибки группы"
    )
    return {
        "title": title,
        "body": "Модуль ИИ отключен. Автоматические рекомендации недоступны.",
        "data": {"by_kind": {}, "by_field": {}, "total": 0, "stub": True},
        "confidence": 0,
        "ai_model": MODEL_NAME,
    }


def build_student_recommendation(stats, error_rows, full_name=None):
    return {
        "title": (
            f"Рекомендации: {full_name}" if full_name else "Рекомендации по подготовке"
        ),
        "body": "Модуль ИИ отключен. Автоматические рекомендации недоступны.",
        "data": {"stats": stats or {}, "stub": True},
        "confidence": 0,
        "ai_model": MODEL_NAME,
    }
