import re
import unicodedata
from difflib import SequenceMatcher

DEFAULT_WEIGHTS = {"content": 0.55, "procedure": 0.20, "timing": 0.15, "grammar": 0.10}

FUZZY_MATCH_THRESHOLD = 0.82


class Verdict:
    def __init__(self, score, passed, parts, errors, stats):
        self.score = score
        self.passed = passed
        self.parts = parts
        self.errors = errors
        self.stats = stats

    def to_dict(self):
        return {
            "score": round(self.score, 2),
            "passed": self.passed,
            "parts": {k: round(v, 2) for k, v in self.parts.items()},
            "stats": self.stats,
            "errors": self.errors,
        }


def normalize(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return " ".join(normalize(v) for v in value)
    text = unicodedata.normalize("NFKC", str(value)).casefold().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a, b):
    a, b = normalize(a), normalize(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _phone_like(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else digits


def score_content(template_fields, reference_card, answer):
    errors = []
    total_weight = 0.0
    earned = 0.0
    matched = 0
    checked = 0

    fields = [
        f for f in (template_fields or []) if isinstance(f, dict) and f.get("key")
    ]
    if not fields:
        fields = [{"key": k, "label": k} for k in (reference_card or {})]

    for field in fields:
        key = field["key"]
        label = field.get("label") or key
        if key not in (reference_card or {}):
            continue
        weight = float(field.get("weight", 1) or 1)
        required = bool(field.get("required", True))
        expected = reference_card.get(key)
        actual = (answer or {}).get(key)
        total_weight += weight
        checked += 1

        if actual in (None, "", [], {}):
            if required:
                errors.append(
                    {
                        "kind": "missing",
                        "field_key": key,
                        "severity": 3,
                        "message": f"Не заполнено обязательное поле «{label}»",
                        "expected": str(expected)[:500],
                        "actual": None,
                    }
                )
            else:
                earned += weight
            continue

        if field.get("type") == "phone":
            ratio = 1.0 if _phone_like(expected) == _phone_like(actual) else 0.0
        else:
            ratio = similarity(expected, actual)

        if ratio >= FUZZY_MATCH_THRESHOLD:
            earned += weight
            matched += 1
        else:
            earned += weight * ratio * 0.5
            errors.append(
                {
                    "kind": "content",
                    "field_key": key,
                    "severity": 3 if required else 2,
                    "message": f"Поле «{label}» не соответствует эталону",
                    "expected": str(expected)[:500],
                    "actual": str(actual)[:500],
                }
            )

    ratio = earned / total_weight if total_weight else 1.0
    return ratio, errors, {"fields_checked": checked, "fields_matched": matched}


def score_procedure(reference_actions, actions):
    reference = [
        normalize(a.get("type") if isinstance(a, dict) else a)
        for a in (reference_actions or [])
    ]
    reference = [a for a in reference if a]
    if not reference:
        return 1.0, [], {"actions_expected": 0, "actions_done": len(actions or [])}

    performed = [
        normalize(a.get("type") if isinstance(a, dict) else a) for a in (actions or [])
    ]
    performed = [a for a in performed if a]

    errors = []
    missing = [a for a in reference if a not in performed]
    for action in missing:
        errors.append(
            {
                "kind": "procedure",
                "field_key": None,
                "severity": 3,
                "message": f"Не выполнено обязательное действие: {action}",
                "expected": action,
                "actual": None,
            }
        )

    order_ratio = SequenceMatcher(None, reference, performed).ratio()
    if order_ratio < 1.0 and not missing:
        errors.append(
            {
                "kind": "procedure",
                "field_key": None,
                "severity": 2,
                "message": "Нарушена последовательность действий с карточкой",
                "expected": " -> ".join(reference),
                "actual": " -> ".join(performed),
            }
        )

    coverage = (len(reference) - len(missing)) / len(reference)
    ratio = 0.7 * coverage + 0.3 * order_ratio
    return (
        ratio,
        errors,
        {
            "actions_expected": len(reference),
            "actions_done": len(performed),
            "actions_missing": len(missing),
        },
    )


def score_timing(duration_ms, time_limit_sec, tolerance_pct=10):
    limit_ms = max(1, int(time_limit_sec) * 1000)
    duration_ms = int(duration_ms or 0)
    allowed = limit_ms * (1 + tolerance_pct / 100.0)
    delta_ms = duration_ms - limit_ms

    if duration_ms <= allowed:
        ratio = 1.0
        errors = []
    else:
        overrun = (duration_ms - allowed) / allowed
        ratio = max(0.0, 1.0 - overrun)
        errors = [
            {
                "kind": "timing",
                "field_key": None,
                "severity": 3 if overrun > 0.5 else 2,
                "message": (
                    f"Превышен норматив времени на {round(delta_ms / 1000, 1)} сек "
                    f"(норматив {time_limit_sec} сек)"
                ),
                "expected": f"{time_limit_sec} сек",
                "actual": f"{round(duration_ms / 1000, 1)} сек",
            }
        ]
    return (
        ratio,
        errors,
        {
            "duration_ms": duration_ms,
            "time_limit_sec": int(time_limit_sec),
            "delta_sec": round(delta_ms / 1000, 1),
            "within_limit": duration_ms <= allowed,
        },
    )


def score_grammar(grammar_errors, max_errors=2):
    count = len(grammar_errors or [])
    if count == 0:
        return 1.0, {"grammar_errors": 0}
    limit = max(1, int(max_errors) + 1)
    return max(0.0, 1.0 - count / (limit * 2)), {"grammar_errors": count}


def evaluate(
    template_fields,
    reference_card,
    reference_actions,
    answer,
    actions,
    duration_ms,
    time_limit_sec,
    grammar_errors=None,
    profile=None,
):
    grammar_errors = list(grammar_errors or [])

    weights = dict(DEFAULT_WEIGHTS)
    pass_score = 70.0
    tolerance = 10
    max_grammar = 2
    limits = {"content": None, "procedure": None, "missing": None}

    if profile is not None:
        weights.update(
            {
                k: float(v)
                for k, v in (profile.error_weights or {}).items()
                if k in DEFAULT_WEIGHTS
            }
        )
        pass_score = float(profile.pass_score)
        tolerance = int(profile.time_overrun_tolerance_pct)
        max_grammar = int(profile.max_grammar_errors)
        limits = {
            "content": profile.max_content_errors,
            "procedure": profile.max_procedure_errors,
            "missing": profile.max_missing_fields,
        }
        if not profile.grammar_check_enabled:
            grammar_errors = []

    total_weight = sum(weights.values()) or 1.0
    weights = {k: v / total_weight for k, v in weights.items()}

    content_ratio, content_errors, content_stats = score_content(
        template_fields, reference_card, answer
    )
    procedure_ratio, procedure_errors, procedure_stats = score_procedure(
        reference_actions, actions
    )
    timing_ratio, timing_errors, timing_stats = score_timing(
        duration_ms, time_limit_sec, tolerance
    )
    grammar_ratio, grammar_stats = score_grammar(grammar_errors, max_grammar)

    score = 100.0 * (
        weights["content"] * content_ratio
        + weights["procedure"] * procedure_ratio
        + weights["timing"] * timing_ratio
        + weights["grammar"] * grammar_ratio
    )
    score = max(0.0, min(100.0, score))

    errors = content_errors + procedure_errors + timing_errors + list(grammar_errors)
    counts = {
        kind: sum(1 for e in errors if e["kind"] == kind)
        for kind in ("content", "procedure", "timing", "grammar", "missing")
    }

    passed = score >= pass_score
    for kind, limit in limits.items():
        if limit is not None and counts.get(kind, 0) > int(limit):
            passed = False
    if counts["grammar"] > max_grammar:
        passed = False

    stats = {
        **content_stats,
        **procedure_stats,
        **timing_stats,
        **grammar_stats,
        "error_counts": counts,
        "pass_score": pass_score,
    }
    parts = {
        "content": 100 * content_ratio,
        "procedure": 100 * procedure_ratio,
        "timing": 100 * timing_ratio,
        "grammar": 100 * grammar_ratio,
    }
    return Verdict(score, passed, parts, errors, stats)
