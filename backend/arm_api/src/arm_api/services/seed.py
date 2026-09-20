"""Начальное наполнение БД. Все шаги идемпотентны: повторный запуск ничего не портит.

python -m arm_api.services.seed            # справочники и настройки
python -m arm_api.services.seed --demo     # + демонстрационные сценарии
python seed_admin.py --username admin ...  # + первый администратор
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from ..core.extensions import db
from ..core.security import PERMISSIONS, ROLE_PERMISSIONS, hash_password
from ..models import (
    CardTemplate,
    GradingProfile,
    IncidentCategory,
    Permission,
    Role,
    Scenario,
    ScenarioOrigin,
    ScenarioStatus,
    SettingScope,
    SystemSetting,
    User,
)
from . import card_schema

CLASSIFIER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "classifier.json"
)

ROLES = {
    "admin": (1, "Администратор"),
    "teacher": (2, "Преподаватель"),
    "student": (3, "Обучающийся"),
}


def seed_rbac():
    have = {p.code: p for p in db.session.execute(select(Permission)).scalars()}
    for code, description in PERMISSIONS.items():
        if code not in have:
            have[code] = Permission(code=code, description=description)
            db.session.add(have[code])
    db.session.flush()

    for code, (role_id, name) in ROLES.items():
        role = (
            db.session.execute(select(Role).where(Role.code == code)).scalars().first()
        )
        if role is None:
            role = Role(id=role_id, code=code, name=name)
            db.session.add(role)
            db.session.flush()
        # набор прав заменяется целиком, чтобы отозванные права не оставались
        role.permissions = [have[p] for p in ROLE_PERMISSIONS[code]]
    db.session.commit()


def seed_categories():
    """Классификатор происшествий: группы - родители, типы - дочерние."""
    with open(CLASSIFIER_PATH, encoding="utf-8") as handle:
        classifier = json.load(handle)

    existing = {
        c.code: c for c in db.session.execute(select(IncidentCategory)).scalars()
    }
    created = 0
    for g_index, group in enumerate(classifier["groups"], start=1):
        parent = existing.get(f"G{g_index:02d}")
        if parent is None:
            parent = IncidentCategory(code=f"G{g_index:02d}", name=group["name"][:128])
            db.session.add(parent)
            db.session.flush()
            existing[parent.code] = parent
            created += 1
        for t_index, item in enumerate(group["types"], start=1):
            code = f"G{g_index:02d}.{t_index:04d}"
            if code in existing:
                continue
            db.session.add(
                IncidentCategory(
                    code=code,
                    name=item["name"],
                    parent_id=parent.id,
                    service_code=item["service"],
                )
            )
            created += 1
    db.session.commit()
    return created


def seed_template():
    have = (
        db.session.execute(
            select(CardTemplate).where(CardTemplate.code == card_schema.TEMPLATE_CODE)
        )
        .scalars()
        .first()
    )
    if have is not None:
        return have
    template = CardTemplate(
        code=card_schema.TEMPLATE_CODE,
        name=card_schema.TEMPLATE_NAME,
        version=1,
        fields=card_schema.TEMPLATE_FIELDS,
        is_active=True,
    )
    db.session.add(template)
    db.session.commit()
    return template


def seed_grading_profile():
    have = (
        db.session.execute(
            select(GradingProfile).where(GradingProfile.is_default.is_(True))
        )
        .scalars()
        .first()
    )
    if have is not None:
        return have
    profile = GradingProfile(
        name="Базовый профиль оценивания",
        max_content_errors=1,
        max_grammar_errors=2,
        max_procedure_errors=0,
        max_missing_fields=0,
        default_time_limit_sec=30,
        time_overrun_tolerance_pct=10,
        pass_score=70,
        grammar_check_enabled=True,
        syntax_rules={},
        error_weights={},
        is_default=True,
    )
    db.session.add(profile)
    db.session.commit()
    return profile


def seed_settings():
    have = set(db.session.execute(select(SystemSetting.key)).scalars())
    for key, scope, value, description, secret, restart in card_schema.DEFAULT_SETTINGS:
        if key not in have:
            db.session.add(
                SystemSetting(
                    key=key,
                    scope=SettingScope(scope),
                    value=value,
                    default_value=value,
                    description=description,
                    is_secret=secret,
                    requires_restart=restart,
                )
            )
    db.session.commit()


def ensure_admin(username, password, full_name="Администратор", email=None):
    """Создает первого администратора. Возвращает True, если создан."""
    exists = db.session.execute(
        select(User.id).where(User.username == username)
    ).first()
    if exists:
        return False
    admin = (
        db.session.execute(select(Role).where(Role.code == "admin")).scalars().first()
    )
    db.session.add(
        User(
            username=username,
            full_name=full_name,
            email=email,
            password_hash=hash_password(password),
            role_id=admin.id,
            is_active=True,
            password_changed_at=datetime.now(timezone.utc),
        )
    )
    db.session.commit()
    return True


# ------------------------------------------------------------------ демо-сценарии

DEMO = [
    {
        "category": "пожар: квартира",
        "title": "Пожар в квартире, есть ребенок",
        "difficulty": 2,
        "legend": {
            "summary": "В квартире на пятом этаже задымление, в комнате находится ребенок.",
            "dialog": [
                "Здравствуйте! У нас в квартире дым, пахнет гарью, мы на пятом этаже!",
                "Помогите, тут ребенок, мы не можем выйти!",
            ],
            "followups": [
                "Профсоюзная улица, дом 12, квартира 48, третий подъезд.",
                "Да, угроза есть, дым идет из кухни, ребенок в комнате.",
                "Пострадавших пока нет, дышать тяжело.",
            ],
            "hints": ["Первым делом уточнить адрес и угрозу людям"],
        },
        "card": {
            "incident_type": "пожар: квартира",
            "incident_details": "Задымление в квартире, есть угроза людям",
            "address_street": "Профсоюзная улица",
            "address_house": "12",
            "address_flat": "48",
            "address_entrance": "3",
            "address_floor": "5",
            "victims": "Нет",
            "services": "Служба 101, Служба 103",
            "description": "Задымление в квартире, в комнате ребенок, выйти не могут",
        },
    },
    {
        "category": "ДТП с пострадавшими",
        "title": "ДТП с пострадавшими на проспекте",
        "difficulty": 3,
        "legend": {
            "summary": "Столкнулись два легковых автомобиля, есть пострадавшие.",
            "dialog": [
                "Тут авария, две машины столкнулись, люди в машинах, кажется, ранены!",
            ],
            "followups": [
                "Ленинский проспект, дом 70, напротив магазина.",
                "Двое пострадавших, один не двигается.",
                "Машины перегородили полосу, разлит бензин.",
            ],
            "hints": ["Вызвать скорую и полицию, уточнить разлив топлива"],
        },
        "card": {
            "incident_type": "ДТП с пострадавшими",
            "incident_details": "Столкновение двух легковых, разлив топлива",
            "address_street": "Ленинский проспект",
            "address_house": "70",
            "address_flat": "",
            "address_entrance": "",
            "address_floor": "",
            "victims": "Двое",
            "services": "Служба 102, Служба 103, Служба 101",
            "description": "Столкнулись две легковые машины, двое пострадавших, разлит бензин",
        },
    },
    {
        "category": "Прорыв водопроводной колонки (проводки)",
        "title": "Прорыв водопроводной колонки во дворе",
        "difficulty": 1,
        "legend": {
            "summary": "Во дворе бьет фонтан из водопроводной колонки, вода заливает подъезд.",
            "dialog": ["Во дворе прорвало трубу, вода хлещет, заливает подъезд."],
            "followups": [
                "Улица Годовикова, дом 9, первый подъезд.",
                "Никто не пострадал, вода уже в подвале.",
            ],
            "hints": ["Направить Мосводоканал, угрозы людям нет"],
        },
        "card": {
            "incident_type": "Прорыв водопроводной колонки (проводки)",
            "incident_details": "Вода заливает подъезд и подвал",
            "address_street": "улица Годовикова",
            "address_house": "9",
            "address_flat": "",
            "address_entrance": "1",
            "address_floor": "",
            "victims": "Нет",
            "services": "Мосводоканал",
            "description": "Прорыв водопроводной колонки во дворе, вода заливает подъезд",
        },
    },
]


def seed_demo():
    template = seed_template()
    created = 0
    for item in DEMO:
        category = (
            db.session.execute(
                select(IncidentCategory).where(
                    IncidentCategory.name.ilike(item["category"]),
                    IncidentCategory.parent_id.is_not(None),
                )
            )
            .scalars()
            .first()
        )
        if category is None:
            continue
        exists = db.session.execute(
            select(Scenario.id).where(Scenario.title == item["title"])
        ).first()
        if exists:
            continue
        db.session.add(
            Scenario(
                title=item["title"],
                category_id=category.id,
                template_id=template.id,
                difficulty=item["difficulty"],
                origin=ScenarioOrigin.MANUAL,
                status=ScenarioStatus.VALIDATED,
                legend=item["legend"],
                reference_card=item["card"],
                reference_actions=list(card_schema.DEFAULT_ACTIONS),
                time_limit_sec=30,
                validated_fields={key: True for key in item["card"]},
                validated_at=datetime.now(timezone.utc),
            )
        )
        created += 1
    db.session.commit()
    return created


def seed_all(demo=False):
    seed_rbac()
    result = {"categories": seed_categories()}
    seed_template()
    seed_grading_profile()
    seed_settings()
    if demo:
        result["demo_scenarios"] = seed_demo()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="добавить демо-сценарии")
    args = parser.parse_args(argv)

    from arm_api import create_app

    app = create_app()
    with app.app_context():
        print("[seed]", seed_all(demo=args.demo))
        username, password = os.environ.get("ADMIN_USERNAME"), os.environ.get(
            "ADMIN_PASSWORD"
        )
        if username and password and ensure_admin(username, password):
            print(f"[seed] создан администратор {username}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[seed] ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
