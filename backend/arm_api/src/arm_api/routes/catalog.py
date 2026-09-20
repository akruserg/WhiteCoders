"""
GET/POST/PATCH /categories       - классификатор происшествий
GET/POST       /card-templates   - шаблоны карточки события (АРМ-112)
GET/POST/PATCH /grading-profiles - критерии успешности и нормативы времени
"""

from flask import Blueprint, request
from sqlalchemy import select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.security import current_user, is_student, require, write_audit
from ..models import CardTemplate, GradingProfile, IncidentCategory
from ..schemas import CardTemplateIn, CategoryIn, GradingProfileIn
from ._helpers import body, commit, get_or_404, item, items

catalog_bp = Blueprint("catalog", __name__)


@catalog_bp.get("/categories")
def list_categories():
    principal = current_user()
    stmt = select(IncidentCategory).order_by(IncidentCategory.code)
    if request.args.get("only_active", "1").lower() in {"1", "true", "yes"}:
        stmt = stmt.where(IncidentCategory.is_active.is_(True))
    if request.args.get("service_code"):
        stmt = stmt.where(IncidentCategory.service_code == request.args["service_code"])

    rows = list(db.session.execute(stmt).scalars())
    if is_student(principal) and principal.service_scope:
        allowed = {c.id for c in principal.service_scope}
        rows = [c for c in rows if c.id in allowed]
    return items(rows)


@catalog_bp.post("/categories")
def create_category():
    principal = require("catalog.manage")
    payload = body(CategoryIn)
    if db.session.execute(
        select(IncidentCategory.id).where(IncidentCategory.code == payload.code)
    ).first():
        raise ApiError("Категория с таким кодом уже существует", 409)

    category = IncidentCategory(
        code=payload.code,
        name=payload.name,
        parent_id=payload.parent_id,
        service_code=payload.service_code,
        is_active=payload.is_active,
    )
    db.session.add(category)
    db.session.flush()
    write_audit(
        db.session, request, principal, "category.create", "category", category.id
    )
    commit()
    return item(category, 201)


@catalog_bp.patch("/categories/<int:category_id>")
def update_category(category_id):
    principal = require("catalog.manage")
    category = get_or_404(IncidentCategory, category_id, "Категория")
    payload = body(CategoryIn)
    category.code = payload.code
    category.name = payload.name
    category.parent_id = payload.parent_id
    category.service_code = payload.service_code
    category.is_active = payload.is_active
    write_audit(
        db.session, request, principal, "category.update", "category", category.id
    )
    commit()
    return item(category)


@catalog_bp.get("/card-templates")
def list_templates():
    current_user()
    stmt = select(CardTemplate).order_by(CardTemplate.code, CardTemplate.version.desc())
    if request.args.get("only_active", "1").lower() in {"1", "true", "yes"}:
        stmt = stmt.where(CardTemplate.is_active.is_(True))
    return items(list(db.session.execute(stmt).scalars()))


@catalog_bp.get("/card-templates/<uuid:template_id>")
def get_template(template_id):
    current_user()
    return item(get_or_404(CardTemplate, template_id, "Шаблон карточки"))


@catalog_bp.post("/card-templates")
def create_template():
    principal = require("catalog.manage")
    payload = body(CardTemplateIn)

    for field in payload.fields:
        if not isinstance(field, dict) or not field.get("key"):
            raise ApiError(
                "Каждое поле шаблона должно быть объектом с ключом key",
                422,
                details={"fields": "ожидается [{key, label, type, required, weight}]"},
            )

    previous = (
        db.session.execute(
            select(CardTemplate)
            .where(CardTemplate.code == payload.code)
            .order_by(CardTemplate.version.desc())
        )
        .scalars()
        .first()
    )
    version = (previous.version + 1) if previous else 1
    if previous is not None:
        previous.is_active = False

    template = CardTemplate(
        code=payload.code,
        name=payload.name,
        version=version,
        fields=payload.fields,
        is_active=True,
    )
    db.session.add(template)
    db.session.flush()
    write_audit(
        db.session,
        request,
        principal,
        "card_template.create",
        "card_template",
        template.id,
        {"version": version},
    )
    commit()
    return item(template, 201)


_PROFILE_FIELDS = (
    "name",
    "category_id",
    "max_content_errors",
    "max_grammar_errors",
    "max_procedure_errors",
    "max_missing_fields",
    "default_time_limit_sec",
    "time_overrun_tolerance_pct",
    "pass_score",
    "grammar_check_enabled",
    "syntax_rules",
    "error_weights",
)


@catalog_bp.get("/grading-profiles")
def list_profiles():
    require("session.manage", "catalog.manage", "scenario.manage")
    return items(
        list(
            db.session.execute(
                select(GradingProfile).order_by(
                    GradingProfile.is_default.desc(), GradingProfile.name
                )
            ).scalars()
        )
    )


@catalog_bp.post("/grading-profiles")
def create_profile():
    principal = require("catalog.manage", "session.manage")
    payload = body(GradingProfileIn)
    profile = GradingProfile(owner_id=principal.id)
    for name in _PROFILE_FIELDS:
        setattr(profile, name, getattr(payload, name))
    if payload.is_default:
        _reset_default()
        profile.is_default = True
    db.session.add(profile)
    db.session.flush()
    write_audit(
        db.session,
        request,
        principal,
        "grading_profile.create",
        "grading_profile",
        profile.id,
    )
    commit()
    return item(profile, 201)


@catalog_bp.patch("/grading-profiles/<uuid:profile_id>")
def update_profile(profile_id):
    principal = require("catalog.manage", "session.manage")
    profile = get_or_404(GradingProfile, profile_id, "Профиль оценивания")
    if (
        profile.owner_id
        and profile.owner_id != principal.id
        and principal.role.code != "admin"
    ):
        raise ApiError("Профиль другого преподавателя", 403)

    payload = body(GradingProfileIn)
    for name in _PROFILE_FIELDS:
        value = getattr(payload, name)
        if value is not None:
            setattr(profile, name, value)
    if payload.is_default:
        _reset_default()
        profile.is_default = True
    write_audit(
        db.session,
        request,
        principal,
        "grading_profile.update",
        "grading_profile",
        profile.id,
    )
    commit()
    return item(profile)


def _reset_default():
    for profile in db.session.execute(
        select(GradingProfile).where(GradingProfile.is_default.is_(True))
    ).scalars():
        profile.is_default = False
