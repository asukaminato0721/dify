"""Lightweight Celery instance for worker health checks.

Importing `app.py` would initialize the full FastAPI app and its extensions.
The health check path only needs broker connectivity, so keep it isolated.
"""

from __future__ import annotations

from celery import Celery

from configs import dify_config
from extensions.ext_celery import get_celery_broker_transport_options, get_celery_ssl_options

celery = Celery(broker=dify_config.CELERY_BROKER_URL)

broker_transport_options = get_celery_broker_transport_options()
if broker_transport_options:
    celery.conf.update(broker_transport_options=broker_transport_options)

ssl_options = get_celery_ssl_options()
if ssl_options:
    celery.conf.update(broker_use_ssl=ssl_options)
