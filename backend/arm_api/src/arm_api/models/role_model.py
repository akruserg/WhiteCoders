from ..core.extensions import db
from .role import role_permissions


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.SmallInteger, primary_key=True)
    code = db.Column(db.String(32), nullable=False, unique=True)
    name = db.Column(db.String(128), nullable=False)

    permissions = db.relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles",
        lazy="selectin",
    )
    users = db.relationship("User", back_populates="role", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "permissions": [permission.code for permission in self.permissions],
        }
