from __future__ import annotations

import logging

from extensions.ext_redis import async_redis_client

logger = logging.getLogger(__name__)


class TaskControlService:
    """Minimal task stop service for the FastAPI port.

    This currently preserves the legacy Redis stop-flag mechanism. It intentionally
    avoids importing the old graph-engine command path so the active FastAPI runtime
    stays decoupled from the legacy workflow stack.
    """

    @staticmethod
    async def stop_task(task_id: str) -> None:
        if not task_id:
            return
        try:
            await async_redis_client.setex(f"generate_task_stopped:{task_id}", 600, 1)
        except Exception:
            logger.warning("Failed to set stop flag for task %s", task_id, exc_info=True)
