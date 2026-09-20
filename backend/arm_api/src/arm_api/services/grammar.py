import re
from functools import lru_cache

# Проверка построена на простых правилах оформления записи (пробелы, регистр,
# парные скобки, смешение алфавитов). Орфографию по словарю она не проверяет.

DEFAULT_RULES = {
    "double_space": True,  # двойные пробелы
    "space_before_punct": True,  # пробел перед знаком препинания
    "no_space_after_punct": True,
    "capital_first": True,  # предложение с заглавной буквы
    "trailing_punct": False,  # точка в конце
    "repeated_word": True,  # повтор слова подряд
    "latin_in_russian": True,  # латиница внутри русского слова (о0, c/с)
    "spelling": True,  # слово, которого нет в словаре русского языка
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


def _double_space(text, key, rules):
    match = re.search(r"\S {2,}\S", text)
    if not match:
        return []
    return [
        _issue(
            key,
            "Лишние пробелы между словами",
            actual=match.group(0),
            expected=" ".join(match.group(0).split()),
            position=match.start(),
        )
    ]


def _space_before_punct(text, key, rules):
    match = re.search(r"\s+([" + re.escape(_PUNCT) + r"])", text)
    if not match:
        return []
    return [
        _issue(
            key,
            "Пробел перед знаком препинания",
            actual=match.group(0),
            expected=match.group(1),
            position=match.start(),
        )
    ]


def _no_space_after_punct(text, key, rules):
    match = re.search(r"([" + re.escape(_PUNCT) + r"])(?=[А-Яа-яЁёA-Za-z])", text)
    if not match:
        return []
    return [
        _issue(
            key,
            "Отсутствует пробел после знака препинания",
            actual=text[match.start() : match.start() + 3],
            position=match.start(),
        )
    ]


def _capital_first(text, key, rules):
    stripped = text.lstrip()
    if not (stripped and stripped[0].isalpha() and stripped[0].islower()):
        return []
    return [
        _issue(
            key,
            "Предложение должно начинаться с заглавной буквы",
            actual=stripped[:20],
            expected=stripped[0].upper() + stripped[1:20],
            position=0,
        )
    ]


def _trailing_punct(text, key, rules):
    if text.rstrip()[-1:] in set(_PUNCT):
        return []
    return [
        _issue(
            key,
            "В конце записи отсутствует знак препинания",
            actual=text.rstrip()[-10:],
            expected=".",
        )
    ]


def _repeated_word(text, key, rules):
    words = _WORD_RE.findall(text)
    for previous, word in zip(words, words[1:]):
        if word.lower() == previous.lower() and len(word) > 2:
            return [_issue(key, f"Повтор слова «{word}»", actual=word)]
    return []


def _latin_in_russian(text, key, rules):
    for word in _WORD_RE.findall(text):
        if _CYR_RE.search(word) and _LAT_RE.search(word):
            return [
                _issue(
                    key,
                    f"Смешение кириллицы и латиницы в слове «{word}»",
                    actual=word,
                    severity=2,
                )
            ]
    return []


_CYR_WORD = re.compile(r"[А-Яа-яЁё]{4,}")
_ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


@lru_cache(maxsize=1)
def _morph():
    """Морфологический словарь (pymorphy3). Нет библиотеки - проверка пропускается."""
    try:
        import pymorphy3
    except ImportError:
        return None
    return pymorphy3.MorphAnalyzer()


def _edits(word):
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = (a + b[1:] for a, b in splits if b)
    swaps = (a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1)
    replaces = (a + c + b[1:] for a, b in splits if b for c in _ALPHABET)
    inserts = (a + c + b for a, b in splits for c in _ALPHABET)
    return set(deletes) | set(swaps) | set(replaces) | set(inserts)


def _suggest(morph, word):
    known = [c for c in _edits(word) if morph.word_is_known(c)]
    if not known:
        return None
    return max(known, key=lambda c: morph.parse(c)[0].score)


def _starts_sentence(text, position):
    return not text[:position].rstrip() or text[:position].rstrip()[-1] in ".!?"


def _spelling(text, key, rules):
    """Слова вне словаря. Не трогаем аббревиатуры, имена внутри предложения и слова
    из условий сценария (known_words): адреса и названия оператор переписывает."""
    morph = _morph()
    if morph is None:
        return []
    known = rules.get("known_words") or ()
    issues = []
    for match in _CYR_WORD.finditer(text):
        word = match.group(0)
        lower = word.lower()
        if word.isupper() or lower in known or morph.word_is_known(lower):
            continue
        if word[0].isupper() and not _starts_sentence(text, match.start()):
            continue
        issues.append(
            _issue(
                key,
                f"Возможная орфографическая ошибка в слове «{word}»",
                actual=word,
                expected=_suggest(morph, lower),
                position=match.start(),
            )
        )
        if len(issues) == 3:
            break
    return issues


def _unbalanced_brackets(text, key, rules):
    if text.count("(") == text.count(")") and text.count("«") == text.count("»"):
        return []
    return [_issue(key, "Непарные скобки или кавычки", actual=text[:40])]


def _min_words(text, key, rules):
    minimum = int(rules.get("min_words") or 0)
    if not minimum or len(_WORD_RE.findall(text)) >= minimum:
        return []
    return [
        _issue(
            key,
            f"Слишком короткая запись (минимум {minimum} сл.)",
            actual=text[:40],
            severity=2,
        )
    ]


# порядок правил определяет порядок замечаний в ответе
_RULES = (
    ("double_space", _double_space),
    ("space_before_punct", _space_before_punct),
    ("no_space_after_punct", _no_space_after_punct),
    ("capital_first", _capital_first),
    ("trailing_punct", _trailing_punct),
    ("repeated_word", _repeated_word),
    ("latin_in_russian", _latin_in_russian),
    ("spelling", _spelling),
    ("unbalanced_brackets", _unbalanced_brackets),
    ("min_words", _min_words),
)


def check_text(text, field_key=None, rules=None):
    rules = {**DEFAULT_RULES, **(rules or {})}
    if not isinstance(text, str) or not text.strip():
        return []

    issues = []
    for name, rule in _RULES:
        if rules[name]:
            issues.extend(rule(text, field_key, rules))
    return issues


def words_of(*texts):
    """Слова из условий сценария: их написание не считается ошибкой."""
    joined = " ".join(str(t) for t in texts if t)
    return {w.lower() for w in _CYR_WORD.findall(joined)}


def check_answer(answer, template_fields, rules=None, known_words=()):
    issues = []
    text_types = {"text", "textarea", "string", None}
    by_key = {f.get("key"): f for f in (template_fields or []) if isinstance(f, dict)}

    for key, value in (answer or {}).items():
        if not isinstance(value, str):
            continue
        field = by_key.get(key, {})
        if field.get("type") not in text_types:
            continue
        field_rules = {
            **(rules or {}),
            **(field.get("syntax_rules") or {}),
            "known_words": known_words,
        }
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
