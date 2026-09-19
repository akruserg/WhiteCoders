from ..core.extensions import db

role_permissions = db.Table(
    "role_permissions",
    db.Column(
        "role_id",
        db.SmallInteger,
        db.ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "permission_code",
        db.String(64),
        db.ForeignKey("permissions.code", ondelete="CASCADE"),
        primary_key=True,
    ),
)
