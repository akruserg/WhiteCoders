"""
GET    /scenarios                      - список с фильтрами
POST   /scenarios                      - ручное создание сценария
POST   /scenarios/generate             - генерация пакета сценариев ИИ
GET    /scenarios/{id}                 - карточка/предпросмотр
PATCH  /scenarios/{id}                 - правка
DELETE /scenarios/{id}                 - перевод в архив
POST   /scenarios/{id}/validate        - полное/частичное утверждение эталона
POST   /scenarios/{id}/corrections     - комментарий преподавателя к сценарию
POST   /scenarios/{id}/grammar-check   - принудительная проверка грамматики
"""

from datetime import datetime, timezone

from flask import Blueprint, request
from sqlalchemy import select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import is_admin, is_student, require, write_audit
from ..models import (
    CardTemplate,
    IncidentCategory,
    Scenario,
    ScenarioCorrection,
    ScenarioOrigin,
    ScenarioStatus,
)
from ..schemas import (
    ScenarioCorrectionIn,
    ScenarioGenerateIn,
    ScenarioIn,
    ScenarioUpdate,
    ScenarioValidateIn,
)
from ..services import ai, grammar
from ._helpers import body, commit, get_or_404, int_arg, ok

scenarios_bp = Blueprint("scenarios", __name__)


def _view(scenario, principal, with_reference=None):
    data = scenario.to_dict()
    if with_reference is None:
        with_reference = not is_student(principal)
    if not with_reference:
        data.pop("reference_card", None)
        data.pop("reference_actions", None)
        data["legend"] = {
            k: v
            for k, v in (data.get("legend") or {}).items()
            if k not in ("hints", "corrections", "followups")
        }
    return data


def _editable(scenario, principal):
    if is_admin(principal):
        return scenario
    if scenario.author_id and scenario.author_id != principal.id:
        raise ApiError("Сценарий другого преподавателя", 403)
    return scenario


def _active_template(template_id=None):
    if template_id:
        return get_or_404(CardTemplate, template_id, "Шаблон карточки")
    template = (
        db.session.execute(
            select(CardTemplate)
            .where(CardTemplate.is_active.is_(True))
            .order_by(CardTemplate.created_at.desc())
        )
        .scalars()
        .first()
    )
    if template is None:
        raise ApiError("Не создан ни один шаблон карточки события", 409)
    return template


def _filter_by_enum(stmt, column, enum_cls, arg):
    value = request.args.get(arg)
    if not value:
        return stmt
    try:
        return stmt.where(column == enum_cls(value))
    except ValueError:
        raise ApiError(f"Некорректный {arg}", 422)


def _apply_list_filters(stmt):
    if int_arg("category_id") is not None:
        stmt = stmt.where(Scenario.category_id == int_arg("category_id"))
    if int_arg("difficulty") is not None:
        stmt = stmt.where(Scenario.difficulty == int_arg("difficulty"))
    stmt = _filter_by_enum(stmt, Scenario.status, ScenarioStatus, "status")
    stmt = _filter_by_enum(stmt, Scenario.origin, ScenarioOrigin, "origin")
    if request.args.get("q"):
        stmt = stmt.where(Scenario.title.ilike(f"%{request.args['q'].strip()}%"))
    return stmt


@scenarios_bp.get("/scenarios")
def list_scenarios():
    principal = require("scenario.read")
    stmt = _apply_list_filters(select(Scenario).order_by(Scenario.created_at.desc()))

    if is_student(principal):
        stmt = stmt.where(Scenario.status == ScenarioStatus.VALIDATED)
        scope = [c.id for c in principal.service_scope]
        if scope:
            stmt = stmt.where(Scenario.category_id.in_(scope))

    return ok(paginate(stmt, serializer=lambda row: _view(row, principal)))


@scenarios_bp.post("/scenarios")
def create_scenario():
    principal = require("scenario.manage")
    payload = body(ScenarioIn)
    get_or_404(IncidentCategory, payload.category_id, "Категория")
    template = _active_template(payload.template_id)

    scenario = Scenario(
        title=payload.title,
        category_id=payload.category_id,
        template_id=template.id,
        difficulty=payload.difficulty,
        origin=ScenarioOrigin.MANUAL,
        status=ScenarioStatus.DRAFT,
        legend=payload.legend,
        reference_card=payload.reference_card,
        reference_actions=payload.reference_actions,
        time_limit_sec=payload.time_limit_sec,
        grading_profile_id=payload.grading_profile_id,
        author_id=principal.id,
    )
    db.session.add(scenario)
    db.session.flush()
    write_audit(
        db.session, request, principal, "scenario.create", "scenario", scenario.id
    )
    commit()
    return ok(_view(scenario, principal), 201)


@scenarios_bp.post("/scenarios/generate")
def generate_scenarios():
    principal = require("scenario.manage")
    payload = body(ScenarioGenerateIn)

    categories = list(
        db.session.execute(
            select(IncidentCategory).where(
                IncidentCategory.id.in_(payload.category_ids)
            )
        ).scalars()
    )
    if not categories:
        raise ApiError("Не найдено ни одной категории из указанных", 422)

    if not ai.is_enabled():
        raise ApiError(
            "Модуль ИИ отключен: автоматическая генерация сценариев недоступна",
            503,
            code="ai_disabled",
        )

    template = _active_template(payload.template_id)
    drafts = ai.generate_scenarios(
        categories,
        count=payload.count,
        difficulty=payload.difficulty,
        template_fields=template.fields,
        time_limit_sec=payload.time_limit_sec,
        hints=payload.hints,
    )

    created = []
    for draft in drafts:
        scenario = Scenario(
            template_id=template.id,
            origin=ScenarioOrigin.AI,
            status=ScenarioStatus.PENDING_REVIEW,
            author_id=principal.id,
            **draft,
        )
        db.session.add(scenario)
        created.append(scenario)
    db.session.flush()

    write_audit(
        db.session,
        request,
        principal,
        "scenario.generate",
        "scenario",
        None,
        {
            "count": len(created),
            "categories": payload.category_ids,
            "model": ai.MODEL_NAME,
        },
    )
    commit()
    return ok(
        {
            "items": [_view(s, principal) for s in created],
            "total": len(created),
            "model": ai.MODEL_NAME,
            "note": "Сценарии требуют подтверждения преподавателем перед занятием",
        },
        201,
    )


@scenarios_bp.get("/scenarios/<uuid:scenario_id>")
def get_scenario(scenario_id):
    principal = require("scenario.read")
    scenario = get_or_404(Scenario, scenario_id, "Сценарий")
    if is_student(principal) and scenario.status is not ScenarioStatus.VALIDATED:
        raise ApiError("Сценарий недоступен", 403)

    data = _view(scenario, principal)
    if not is_student(principal):
        template = db.session.get(CardTemplate, scenario.template_id)
        data["preview"] = {
            "template_fields": template.fields if template else [],
            "highlighted": [
                {
                    "key": field.get("key"),
                    "label": field.get("label"),
                    "expected": (scenario.reference_card or {}).get(field.get("key")),
                    "validated": bool(
                        (scenario.validated_fields or {}).get(field.get("key"))
                    ),
                }
                for field in (template.fields if template else [])
                if isinstance(field, dict)
            ],
            "expected_actions": scenario.reference_actions,
        }
        data["corrections"] = [c.to_dict() for c in scenario.corrections]
    return ok(data)


@scenarios_bp.patch("/scenarios/<uuid:scenario_id>")
def update_scenario(scenario_id):
    principal = require("scenario.manage")
    scenario = _editable(get_or_404(Scenario, scenario_id, "Сценарий"), principal)
    payload = body(ScenarioUpdate)

    changed = {}
    for name in (
        "title",
        "difficulty",
        "legend",
        "reference_card",
        "reference_actions",
        "time_limit_sec",
        "grading_profile_id",
    ):
        value = getattr(payload, name, None)
        if value is not None:
            setattr(scenario, name, value)
            changed[name] = True
    if {"reference_card", "reference_actions", "legend"} & set(changed):
        scenario.status = ScenarioStatus.DRAFT
        scenario.validated_fields = {}
        scenario.validated_by = None
        scenario.validated_at = None

    write_audit(
        db.session,
        request,
        principal,
        "scenario.update",
        "scenario",
        scenario.id,
        changed,
    )
    commit()
    return ok(_view(scenario, principal))


@scenarios_bp.delete("/scenarios/<uuid:scenario_id>")
def archive_scenario(scenario_id):
    principal = require("scenario.manage")
    scenario = _editable(get_or_404(Scenario, scenario_id, "Сценарий"), principal)
    scenario.status = ScenarioStatus.ARCHIVED
    write_audit(
        db.session, request, principal, "scenario.archive", "scenario", scenario.id
    )
    commit()
    return ok({"status": "archived", "id": str(scenario.id)})


@scenarios_bp.post("/scenarios/<uuid:scenario_id>/validate")
def validate_scenario(scenario_id):
    principal = require("scenario.validate")
    scenario = _editable(get_or_404(Scenario, scenario_id, "Сценарий"), principal)
    if scenario.status is ScenarioStatus.ARCHIVED:
        raise ApiError("Сценарий в архиве, утверждать его нельзя", 409)
    payload = body(ScenarioValidateIn)

    validated = dict(scenario.validated_fields or {})
    now = datetime.now(timezone.utc)

    if payload.full:
        validated = {key: True for key in (scenario.reference_card or {})}
        scenario.status = ScenarioStatus.VALIDATED
    else:
        unknown = [
            f for f in payload.fields if f not in (scenario.reference_card or {})
        ]
        if unknown:
            raise ApiError(f"Неизвестные поля эталона: {unknown}", 422)
        for field in payload.fields:
            validated[field] = True
        all_keys = set(scenario.reference_card or {})
        scenario.status = (
            ScenarioStatus.VALIDATED
            if all_keys and all_keys <= set(validated)
            else ScenarioStatus.PARTIALLY_VALIDATED
        )

    scenario.validated_fields = validated
    scenario.validated_by = principal.id
    scenario.validated_at = now
    if payload.comment:
        db.session.add(
            ScenarioCorrection(
                scenario_id=scenario.id,
                author_id=principal.id,
                comment=payload.comment,
                applied=False,
            )
        )

    write_audit(
        db.session,
        request,
        principal,
        "scenario.validate",
        "scenario",
        scenario.id,
        {"status": scenario.status.value, "fields": list(validated)},
    )
    commit()
    return ok(_view(scenario, principal))


@scenarios_bp.post("/scenarios/<uuid:scenario_id>/corrections")
def correct_scenario(scenario_id):
    principal = require("scenario.manage")
    scenario = _editable(get_or_404(Scenario, scenario_id, "Сценарий"), principal)
    payload = body(ScenarioCorrectionIn)

    correction = ScenarioCorrection(
        scenario_id=scenario.id,
        author_id=principal.id,
        comment=payload.comment,
    )
    db.session.add(correction)

    if payload.apply_now:
        patch, explanation = ai.apply_correction(scenario, payload.comment)
        if patch:  # нечего править - утвержденный сценарий не трогаем
            for key, value in patch.items():
                setattr(scenario, key, value)
            scenario.status = ScenarioStatus.PENDING_REVIEW
            scenario.validated_fields = {}
            correction.applied = True
            correction.applied_at = datetime.now(timezone.utc)
        correction.result = {"patch": list(patch), "explanation": explanation}

    write_audit(
        db.session,
        request,
        principal,
        "scenario.correction",
        "scenario",
        scenario.id,
        {"applied": correction.applied},
    )
    commit()
    return ok(
        {"correction": correction.to_dict(), "scenario": _view(scenario, principal)},
        201,
    )


@scenarios_bp.post("/scenarios/<uuid:scenario_id>/grammar-check")
def check_scenario_grammar(scenario_id):
    principal = require("scenario.manage")
    scenario = _editable(get_or_404(Scenario, scenario_id, "Сценарий"), principal)
    issues = grammar.check_scenario(
        {
            "legend": scenario.legend,
            "reference_card": scenario.reference_card,
        }
    )
    return ok({"scenario_id": str(scenario.id), "issues": issues, "total": len(issues)})
