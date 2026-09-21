import pytest

from arm_api.services import attestation, reporting


def norm(raw=None, default=70):
    return attestation.normalize(raw if raw is not None else {}, default)


def test_defaults_use_system_pass_score():
    cfg, errors = norm({})
    assert errors == [] and cfg["pass_score"] == 70.0
    assert (
        cfg["min_attempts"] == 1
        and cfg["certificate"] is True
        and cfg["valid_months"] == 12
    )


def test_custom_parameters_are_accepted():
    cfg, errors = norm(
        {"pass_score": 85, "min_attempts": 3, "certificate": False, "valid_months": 6}
    )
    assert errors == [] and cfg == {
        "pass_score": 85.0,
        "min_attempts": 3,
        "certificate": False,
        "valid_months": 6,
    }


@pytest.mark.parametrize(
    "raw, part",
    [
        ({"pass_score": 0}, "pass_score"),
        ({"pass_score": 101}, "pass_score"),
        ({"pass_score": "много"}, "pass_score"),
        ({"pass_score": True}, "pass_score"),
        ({"min_attempts": 0}, "min_attempts"),
        ({"min_attempts": 2.5}, "min_attempts"),
        ({"certificate": "да"}, "certificate"),
        ({"valid_months": 1000}, "valid_months"),
        ({"magic": 1}, "magic"),
    ],
)
def test_invalid_parameters_are_reported(raw, part):
    cfg, errors = norm(raw)
    assert cfg is None and any(part in e for e in errors)


def test_non_object_is_rejected():
    assert attestation.normalize([1], 70)[0] is None


def test_decision_needs_enough_attempts_and_average():
    assert attestation.decide([80, 90, 70], 75, 3)["passed"] is True
    assert attestation.decide([80, 90], 75, 3) == {
        "average": 85.0,
        "attempts": 2,
        "passed": False,
        "enough_attempts": False,
    }
    assert attestation.decide([60, 70, 75], 75, 3)["passed"] is False
    empty = attestation.decide([], 70, 1)
    assert empty["passed"] is False and empty["average"] == 0.0


def test_border_average_passes():
    assert attestation.decide([75.0, 75.0], 75, 2)["passed"] is True


def test_student_sees_score_but_not_errors_during_attestation():
    full = {
        "attempt_id": "a",
        "session_id": "s",
        "seq": 1,
        "status": "evaluated",
        "score": 80.0,
        "auto_score": 80.0,
        "passed": True,
        "duration_ms": 1000,
        "time_limit_sec": 30,
        "delta_sec": 0.0,
        "expert_comment": "x",
        "breakdown": {"parts": [1]},
        "errors": [{"expected": "секрет"}],
    }
    hidden = attestation.redact(full)
    assert hidden["score"] == 80.0 and hidden["passed"] is True
    assert (
        "errors" not in hidden
        and "breakdown" not in hidden
        and "expert_comment" not in hidden
    )
    assert "секрет" not in str(hidden) and hidden["details_hidden"]


def test_protocol_rows_and_anonymised_names():
    exam = {
        "config": {"pass_score": 75.0, "min_attempts": 2},
        "students": [
            {
                "full_name": "Иванов",
                "attempts": 3,
                "average": 88.0,
                "passed": True,
                "enough_attempts": True,
                "certificate": "АРМ112-1",
            },
            {
                "full_name": "Петров",
                "attempts": 1,
                "average": 90.0,
                "passed": False,
                "enough_attempts": False,
                "certificate": None,
            },
            {
                "full_name": "Сидоров",
                "attempts": 2,
                "average": 50.0,
                "passed": False,
                "enough_attempts": True,
                "certificate": None,
            },
        ],
        "passed": 1,
        "total": 3,
    }
    rows = reporting.attestation_rows(exam)
    text = " | ".join(str(c) for r in rows for c in r)
    assert "Проходной балл: 75" in text and "аттестован" in text
    assert "недостаточно карточек" in text and "не аттестован" in text
    assert rows[-1] == ["Итого аттестовано", "1 из 3"]
    assert any(r and r[-1] == "АРМ112-1" for r in rows)
