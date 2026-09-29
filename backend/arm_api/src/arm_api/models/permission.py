from ..core.extensions import db


class Permission(db.Model):
    __tablename__ = "permissions"

    code = db.Column(db.String(64), primary_key=True)
    description = db.Column(db.String(255), nullable=False)

    roles = db.relationship(
        "Role",
        secondary="role_permissions",
        back_populates="permissions",
    )

    def to_dict(self):
        return {
            "code": self.code,
            "description": self.description,
        }
