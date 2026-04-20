from extensions.ext_database import db


def init_app(app):
    with app.app_context():
        if db.session_maker is None:
            raise RuntimeError("Database manager is not initialized.")
