from core.db.session_factory import configure_sync_session_factory
from extensions.ext_database import db


def init_app(app):
    with app.app_context():
        configure_sync_session_factory(db.sync_engine)
