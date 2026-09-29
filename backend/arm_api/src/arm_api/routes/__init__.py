from .auth import auth_bp
from .catalog import catalog_bp
from .internal import internal_bp
from .materials import materials_bp
from .meta import meta_bp
from .reports import reports_bp
from .results import results_bp
from .scenarios import scenarios_bp
from .sessions import sessions_bp
from .system import system_bp
from .updates import updates_bp
from .users import users_bp
from .workstations import workstations_bp

API_BLUEPRINTS = (
    auth_bp,
    users_bp,
    catalog_bp,
    scenarios_bp,
    materials_bp,
    sessions_bp,
    results_bp,
    reports_bp,
    system_bp,
    updates_bp,
    internal_bp,
    workstations_bp,
)


def register_routes(app):
    prefix = app.config.get("API_PREFIX", "/api/v1")
    for blueprint in API_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=prefix)
    app.register_blueprint(meta_bp, url_prefix=prefix)
    app.add_url_rule("/health", "health_root", _liveness)


def _liveness():
    from flask import jsonify

    return jsonify({"status": "ok"})
