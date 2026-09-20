import uuid as uuid_mod

from flask import request


class ValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


class Field:
    __slots__ = (
        "type",
        "required",
        "default",
        "choices",
        "min",
        "max",
        "min_len",
        "max_len",
        "item_type",
        "nullable",
    )

    def __init__(
        self,
        type="str",
        required=False,
        default=None,
        choices=None,
        min=None,
        max=None,
        min_len=None,
        max_len=None,
        item_type=None,
        nullable=False,
    ):
        self.type = type
        self.required = required
        self.default = default
        self.choices = choices
        self.min = min
        self.max = max
        self.min_len = min_len
        self.max_len = max_len
        self.item_type = item_type
        self.nullable = nullable

    def _cast(self, name, value):
        t = self.type
        if t == "str":
            if not isinstance(value, str):
                raise ValueError("ожидается строка")
            return value.strip()
        if t == "int":
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise ValueError("ожидается целое число")
            return int(value)
        if t == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError("ожидается число")
            return float(value)
        if t == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            raise ValueError("ожидается true/false")
        if t == "uuid":
            try:
                return uuid_mod.UUID(str(value))
            except ValueError:
                raise ValueError("ожидается UUID")
        if t == "dict":
            if not isinstance(value, dict):
                raise ValueError("ожидается объект")
            return value
        if t == "list":
            if not isinstance(value, list):
                raise ValueError("ожидается массив")
            if self.item_type:
                item_field = Field(self.item_type)
                return [item_field._cast(name, item) for item in value]
            return value
        if t == "any":
            return value
        raise ValueError(f"неизвестный тип {t}")

    def validate(self, name, value):
        if value is None:
            if self.nullable:
                return None
            raise ValueError("значение не может быть null")

        value = self._cast(name, value)

        if self.choices is not None and value not in self.choices:
            raise ValueError(
                "допустимые значения: " + ", ".join(map(str, self.choices))
            )
        if self.min is not None and value < self.min:
            raise ValueError(f"минимальное значение {self.min}")
        if self.max is not None and value > self.max:
            raise ValueError(f"максимальное значение {self.max}")
        if self.min_len is not None and len(value) < self.min_len:
            raise ValueError(f"минимальная длина {self.min_len}")
        if self.max_len is not None and len(value) > self.max_len:
            raise ValueError(f"максимальная длина {self.max_len}")
        return value


class SchemaMeta(type):
    def __new__(mcls, name, bases, ns):
        fields = {}
        for base in bases:
            fields.update(getattr(base, "_fields", {}))
        for key, value in list(ns.items()):
            if isinstance(value, Field):
                fields[key] = value
                ns.pop(key)
        ns["_fields"] = fields
        return super().__new__(mcls, name, bases, ns)


class Schema(metaclass=SchemaMeta):
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)

    @classmethod
    def load(cls, data):
        if not isinstance(data, dict):
            raise ValidationError({"_body": "ожидается JSON-объект"})

        values, errors = {}, {}
        unknown = set(data) - set(cls._fields)
        for name, field in cls._fields.items():
            if name not in data:
                if field.required:
                    errors[name] = "обязательное поле"
                else:
                    default = field.default
                    values[name] = default() if callable(default) else default
                continue
            try:
                values[name] = field.validate(name, data[name])
            except ValueError as exc:
                errors[name] = str(exc)
        if errors:
            raise ValidationError(errors)
        instance = cls(**values)
        instance._unknown = unknown
        return instance

    @classmethod
    def from_request(cls):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        return cls.load(data)

    @classmethod
    def from_query(cls):
        data = {}
        for name, field in cls._fields.items():
            if name not in request.args:
                continue
            if field.type == "list":
                data[name] = [
                    v
                    for raw in request.args.getlist(name)
                    for v in raw.split(",")
                    if v != ""
                ]
            else:
                data[name] = request.args.get(name)
        return cls.load(data)

    def to_dict(self):
        return {name: getattr(self, name, None) for name in self._fields}


class LoginIn(Schema):
    username = Field("str", required=True, min_len=1, max_len=64)
    password = Field("str", required=True, min_len=1, max_len=256)


class MfaIn(Schema):
    mfa_token = Field("str", required=True)
    code = Field("str", required=True, min_len=6, max_len=8)


class RefreshIn(Schema):
    refresh_token = Field("str", required=True)


class PasswordChangeIn(Schema):
    old_password = Field("str", required=True)
    new_password = Field("str", required=True, min_len=10, max_len=256)


class UserCreate(Schema):
    username = Field("str", required=True, min_len=3, max_len=64)
    full_name = Field("str", required=True, max_len=255)
    password = Field("str", required=True, max_len=256)
    role_code = Field("str", required=True, choices=["admin", "teacher", "student"])
    email = Field("str", max_len=255, nullable=True)
    mfa_enabled = Field("bool", default=False)
    category_ids = Field("list", item_type="int", default=list)


class UserUpdate(Schema):
    full_name = Field("str", max_len=255)
    email = Field("str", max_len=255, nullable=True)
    role_code = Field("str", choices=["admin", "teacher", "student"])
    is_active = Field("bool")
    mfa_enabled = Field("bool")
    category_ids = Field("list", item_type="int")


class PasswordResetIn(Schema):
    new_password = Field("str", required=True, min_len=10, max_len=256)


class GroupIn(Schema):
    name = Field("str", required=True, max_len=128)
    teacher_id = Field("uuid", nullable=True)
    member_ids = Field("list", item_type="uuid", default=list)


class MembersIn(Schema):
    user_ids = Field("list", item_type="uuid", required=True)


class CategoryIn(Schema):
    code = Field("str", required=True, max_len=32)
    name = Field("str", required=True, max_len=128)
    parent_id = Field("int", nullable=True)
    service_code = Field("str", max_len=64, nullable=True)
    is_active = Field("bool", default=True)


class CardTemplateIn(Schema):
    code = Field("str", required=True, max_len=64)
    name = Field("str", required=True, max_len=255)
    fields = Field("list", required=True, min_len=1)


class GradingProfileIn(Schema):
    name = Field("str", required=True, max_len=128)
    category_id = Field("int", nullable=True)
    max_content_errors = Field("int", default=0, min=0, max=100)
    max_grammar_errors = Field("int", default=2, min=0, max=100)
    max_procedure_errors = Field("int", default=0, min=0, max=100)
    max_missing_fields = Field("int", default=0, min=0, max=100)
    default_time_limit_sec = Field("int", default=30, min=5, max=3600)
    time_overrun_tolerance_pct = Field("int", default=10, min=0, max=100)
    pass_score = Field("float", default=70.0, min=0, max=100)
    grammar_check_enabled = Field("bool", default=True)
    syntax_rules = Field("dict", default=dict)
    error_weights = Field("dict", default=dict)
    is_default = Field("bool", default=False)


class ScenarioIn(Schema):
    title = Field("str", required=True, max_len=255)
    category_id = Field("int", required=True)
    template_id = Field("uuid", required=True)
    difficulty = Field("int", default=1, min=1, max=5)
    legend = Field("dict", required=True)
    reference_card = Field("dict", required=True)
    reference_actions = Field("list", default=list)
    time_limit_sec = Field("int", default=30, min=5, max=3600)
    grading_profile_id = Field("uuid", nullable=True)


class ScenarioUpdate(Schema):
    title = Field("str", max_len=255)
    difficulty = Field("int", min=1, max=5)
    legend = Field("dict")
    reference_card = Field("dict")
    reference_actions = Field("list")
    time_limit_sec = Field("int", min=5, max=3600)
    grading_profile_id = Field("uuid", nullable=True)


class ScenarioGenerateIn(Schema):
    category_ids = Field("list", item_type="int", required=True, min_len=1)
    count = Field("int", default=5, min=1, max=50)
    difficulty = Field("int", default=2, min=1, max=5)
    template_id = Field("uuid", nullable=True)
    time_limit_sec = Field("int", default=30, min=5, max=3600)
    hints = Field("str", default="", max_len=2000)


class ScenarioValidateIn(Schema):
    fields = Field("list", item_type="str", default=list)
    full = Field("bool", default=False)
    comment = Field("str", default="", max_len=2000)


class ScenarioCorrectionIn(Schema):
    comment = Field("str", required=True, min_len=3, max_len=2000)
    apply_now = Field("bool", default=True)


class MaterialIn(Schema):
    title = Field("str", required=True, max_len=255)
    category_id = Field("int", nullable=True)


class SessionCreate(Schema):
    title = Field("str", required=True, max_len=255)
    mode = Field("str", default="cards", choices=["cards", "card_actions", "mixed"])
    question_source = Field(
        "str", default="generated", choices=["generated", "student", "mixed"]
    )
    group_id = Field("uuid", nullable=True)
    participant_ids = Field("list", item_type="uuid", default=list)
    category_ids = Field("list", item_type="int", default=list)
    difficulty_min = Field("int", default=1, min=1, max=5)
    difficulty_max = Field("int", default=5, min=1, max=5)
    time_limit_sec = Field("int", default=30, min=5, max=3600)
    grading_profile_id = Field("uuid", nullable=True)
    channel = Field("str", default="text", choices=["text", "voip"])


class SessionUpdate(Schema):
    title = Field("str", max_len=255)
    category_ids = Field("list", item_type="int")
    difficulty_min = Field("int", min=1, max=5)
    difficulty_max = Field("int", min=1, max=5)
    time_limit_sec = Field("int", min=5, max=3600)
    grading_profile_id = Field("uuid", nullable=True)
    channel = Field("str", choices=["text", "voip"])


class SubmitIn(Schema):
    answer = Field("dict", required=True)
    actions = Field("list", default=list)


class CallMessageIn(Schema):
    text = Field("str", required=True, min_len=1, max_len=4000)


class ExpertGradeIn(Schema):
    score = Field("float", required=True, min=0, max=100)
    comment = Field("str", default="", max_len=4000)


class ReportCreateIn(Schema):
    kind = Field(
        "str",
        required=True,
        choices=[
            "session",
            "student_progress",
            "group_progress",
            "error_heatmap",
            "system_usage",
            "security_audit",
        ],
    )
    format = Field("str", default="json", choices=["json", "csv", "xlsx", "pdf"])
    session_id = Field("uuid", nullable=True)
    params = Field("dict", default=dict)


class InsightGenerateIn(Schema):
    kind = Field(
        "str",
        required=True,
        choices=["group_typical_errors", "student_recommendation", "session_summary"],
    )
    session_id = Field("uuid", nullable=True)
    target_user_id = Field("uuid", nullable=True)
    target_group_id = Field("uuid", nullable=True)
    publish = Field("bool", default=False)


class CertificateIn(Schema):
    user_id = Field("uuid", required=True)
    session_id = Field("uuid", nullable=True)
    valid_months = Field("int", default=12, min=1, max=120)


class SettingUpdateIn(Schema):
    value = Field("any", required=True)


class AlertActionIn(Schema):
    comment = Field("str", default="", max_len=1000)


class BackupCreateIn(Schema):
    kind = Field("str", default="full", choices=["full", "incremental"])


class PageQuery(Schema):
    page = Field("int", default=1, min=1)
    per_page = Field("int", default=50, min=1, max=200)
