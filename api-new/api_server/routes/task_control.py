from __future__ import annotations

from typing import TypedDict

from fastapi import APIRouter, Request

from api_server.errors import forbidden
from api_server.services.task_control import TaskControlService
from api_server.services.webapp_context import WebappContextService

router = APIRouter(tags=["task-control"])


class ResultResponseDict(TypedDict):
    result: str


@router.post("/api/completion-messages/{task_id}/stop")
async def stop_completion_task(request: Request, task_id: str) -> ResultResponseDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode != "completion":
        raise forbidden(
            "not_completion_app",
            "Please check if your Completion app mode matches the right API route.",
        )
    await TaskControlService.stop_task(task_id)
    return {"result": "success"}


@router.post("/api/chat-messages/{task_id}/stop")
async def stop_chat_task(request: Request, task_id: str) -> ResultResponseDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode not in {"chat", "agent-chat", "advanced-chat"}:
        raise forbidden("not_chat_app", "Please check if your app mode matches the right API route.")
    await TaskControlService.stop_task(task_id)
    return {"result": "success"}


@router.post("/api/workflows/tasks/{task_id}/stop")
async def stop_workflow_task(request: Request, task_id: str) -> ResultResponseDict:
    context = await WebappContextService.resolve(request)
    if context.app.mode != "workflow":
        raise forbidden("not_workflow_app", "Please check if your Workflow app mode matches the right API route.")
    await TaskControlService.stop_task(task_id)
    return {"result": "success"}
