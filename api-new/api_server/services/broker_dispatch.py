"""Async-safe Celery broker dispatch helpers for the FastAPI runtime.

The active FastAPI routes should not block the event loop while publishing
tasks. These helpers offload `.delay()` and `.apply_async()` submissions to a
worker thread while the larger task stack remains sync-first.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast


async def delay_task(task: object, *args: object, **kwargs: object) -> None:
    await asyncio.to_thread(cast(Any, task).delay, *args, **kwargs)


async def apply_async_task(task: object, *args: object, **kwargs: object) -> None:
    await asyncio.to_thread(cast(Any, task).apply_async, *args, **kwargs)
