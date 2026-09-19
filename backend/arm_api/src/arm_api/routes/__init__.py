from .sessions import sessions_bp 


def reg_routes(app):
    app.register_blueprint(sessions_bp)