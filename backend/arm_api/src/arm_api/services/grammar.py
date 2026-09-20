import re

### полный кринж переписать!!!

DEFAULT_RULES = {
    "double_space": True,  # двойные пробелы
    "space_before_punct": True,  # пробел перед знаком препинания
    "no_space_after_punct": True,
    "capital_first": True,  # предложение с заглавной буквы
    "trailing_punct": False,  # точка в конце
    "repeated_word": True,  # повтор слова подряд
    "latin_in_russian": True,  # латиница внутри русского слова (о0, c/с)
    "unbalanced_brackets": True,
    "min_words": 0,  # минимум слов в текстовом поле
}

_PUNCT = ".,;:!?"
_WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]*")
_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_LAT_RE = re.compile(r"[A-Za-z]")


def _issue(field_key, message, actual=None, expected=None, position=None, severity=1):
    return {
        "kind": "grammar",
        "field_key": field_key,
        "message": message,
        "expected": expected,
        "actual": actual,
        "position": position,
        "severity": severity,
    }


def check_text(text, field_key=None, rules=None):
    rules = {**DEFAULT_RULES, **(rules or {})}
    issues = []
    if not isinstance(text, str) or not text.strip():
        return issues

    if rules["double_space"]:
        match = re.search(r"\S {2,}\S", text)
        if match:
            issues.append(
                _issue(
                    field_key,
                    "Лишние пробелы между словами",
                    actual=match.group(0),
                    expected=" ".join(match.group(0).split()),
                    position=match.start(),
                )
            )

    if rules["space_before_punct"]:
        match = re.search(r"\s+([" + re.escape(_PUNCT) + r"])", text)
        if match:
            issues.append(
                _issue(
                    field_key,
                    "Пробел перед знаком препинания",
                    actual=match.group(0),
                    expected=match.group(1),
                    position=match.start(),
                )
            )

    if rules["no_space_after_punct"]:
        match = re.search(r"([" + re.escape(_PUNCT) + r"])(?=[А-Яа-яЁёA-Za-z])", text)
        if match:
            issues.append(
                _issue(
                    field_key,
                    "Отсутствует пробел после знака препинания",
                    actual=text[match.start() : match.start() + 3],
                    position=match.start(),
                )
            )

    if rules["capital_first"]:
        stripped = text.lstrip()
        if stripped and stripped[0].isalpha() and stripped[0].islower():
            issues.append(
                _issue(
                    field_key,
                    "Предложение должно начинаться с заглавной буквы",
                    actual=stripped[:20],
                    expected=stripped[0].upper() + stripped[1:20],
                    position=0,
                )
            )

    if rules["trailing_punct"] and text.rstrip()[-1:] not in set(_PUNCT):
        issues.append(
            _issue(
                field_key,
                "В конце записи отсутствует знак препинания",
                actual=text.rstrip()[-10:],
                expected=".",
            )
        )

    if rules["repeated_word"]:
        words = _WORD_RE.findall(text)
        for i in range(1, len(words)):
            if words[i].lower() == words[i - 1].lower() and len(words[i]) > 2:
                issues.append(
                    _issue(field_key, f"Повтор слова «{words[i]}»", actual=words[i])
                )
                break

    if rules["latin_in_russian"]:
        for word in _WORD_RE.findall(text):
            if _CYR_RE.search(word) and _LAT_RE.search(word):
                issues.append(
                    _issue(
                        field_key,
                        f"Смешение кириллицы и латиницы в слове «{word}»",
                        actual=word,
                        severity=2,
                    )
                )
                break

    if rules["unbalanced_brackets"]:
        if text.count("(") != text.count(")") or text.count("«") != text.count("»"):
            issues.append(
                _issue(field_key, "Непарные скобки или кавычки", actual=text[:40])
            )

    min_words = int(rules.get("min_words") or 0)
    if min_words and len(_WORD_RE.findall(text)) < min_words:
        issues.append(
            _issue(
                field_key,
                f"Слишком короткая запись (минимум {min_words} сл.)",
                actual=text[:40],
                severity=2,
            )
        )

    return issues


def check_answer(answer, template_fields, rules=None):
    issues = []
    text_types = {"text", "textarea", "string", None}
    by_key = {f.get("key"): f for f in (template_fields or []) if isinstance(f, dict)}

    for key, value in (answer or {}).items():
        if not isinstance(value, str):
            continue
        field = by_key.get(key, {})
        if field.get("type") not in text_types:
            continue
        field_rules = {**(rules or {}), **(field.get("syntax_rules") or {})}
        issues.extend(check_text(value, field_key=key, rules=field_rules))
    return issues


def check_scenario(scenario_like, rules=None):
    issues = []
    legend = scenario_like.get("legend") or {}
    for line in legend.get("dialog", []) or []:
        issues.extend(check_text(line, field_key="legend.dialog", rules=rules))
    issues.extend(
        check_text(legend.get("summary"), field_key="legend.summary", rules=rules)
    )
    for key, value in (scenario_like.get("reference_card") or {}).items():
        if isinstance(value, str):
            issues.extend(
                check_text(value, field_key=f"reference_card.{key}", rules=rules)
            )
    return issues
