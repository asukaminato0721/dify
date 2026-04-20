from __future__ import annotations

import logging
import sys

from celery import Celery
from uvicorn import run

from app_factory import create_app

HOST = "0.0.0.0"
PORT = 5001
logger = logging.getLogger(__name__)

app = create_app()
celery = app.extensions["celery"]
if not isinstance(celery, Celery):  # pragma: no cover - startup invariant
    raise RuntimeError("Celery extension is not initialized.")


def log_startup_banner(host: str, port: int) -> None:
    debugger_attached = sys.gettrace() is not None
    logger.info("Serving Dify API via Uvicorn")
    logger.info("Bound to http://%s:%s", host, port)
    logger.info("Debugger attached: %s", "on" if debugger_attached else "off")
    logger.info("Press CTRL+C to quit")


def main() -> None:
    log_startup_banner(HOST, PORT)
    run("app:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
