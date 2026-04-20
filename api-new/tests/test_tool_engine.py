from __future__ import annotations

from typing import Any, cast

from api_server.models.app import Message as FastAPIMessage
import core.tools.tool_engine as tool_engine_module
from core.app.entities.app_invoke_entities import InvokeFrom
from core.app.entities.queue_entities import QueueMessageFileEvent
from core.tools.tool_engine import ToolEngine
from graphon.file import FileTransferMethod
from graphon.file import FileType


class _SessionStub:
    added: list[object]

    def __init__(self) -> None:
        self.added = []

    def __enter__(self) -> "_SessionStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def add(self, obj: object) -> None:
        if getattr(obj, "id", None) is None:
            setattr(obj, "id", "message-file-1")
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def refresh(self, _obj: object) -> None:
        return None


class _SessionMakerStub:
    session: _SessionStub

    def __init__(self) -> None:
        self.session = _SessionStub()

    def begin(self) -> _SessionStub:
        return self.session


def test_create_message_files_returns_queue_ready_payloads() -> None:
    session_maker = _SessionMakerStub()
    original_get_sync_session_maker = tool_engine_module.session_factory.get_sync_session_maker
    tool_engine_module.session_factory.get_sync_session_maker = cast(Any, lambda: session_maker)
    try:
        events = ToolEngine._create_message_files(
            tool_messages=[
                cast(
                    Any,
                    type(
                        "_Binary",
                        (),
                        {
                            "mimetype": "image/png",
                            "url": "/files/tools/tool-file-1.png",
                        },
                    )(),
                )
            ],
            agent_message=FastAPIMessage(
                id="message-1",
                app_id="app-1",
                model_provider=None,
                model_id=None,
                override_model_configs=None,
                conversation_id="conversation-1",
                inputs={},
                query="hello",
                message={},
                message_tokens=0,
                message_unit_price=0,
                message_price_unit=0,
                answer="",
                answer_tokens=0,
                answer_unit_price=0,
                answer_price_unit=0,
                parent_message_id=None,
                provider_response_latency=0.0,
                total_price=0,
                currency="USD",
                status="normal",
                error=None,
                message_metadata=None,
                invoke_from="web-app",
                from_source="api",
                from_end_user_id="end-user-1",
                from_account_id=None,
                agent_based=False,
                workflow_run_id=None,
                app_mode="agent-chat",
            ),
            invoke_from=InvokeFrom.WEB_APP,
            user_id="end-user-1",
        )
    finally:
        tool_engine_module.session_factory.get_sync_session_maker = original_get_sync_session_maker

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, QueueMessageFileEvent)
    assert event.message_file_id == "message-file-1"
    assert event.message_id == "message-1"
    assert event.type == FileType.IMAGE
    assert event.transfer_method == FileTransferMethod.TOOL_FILE
    assert event.url == "/files/tools/tool-file-1.png"
    assert event.upload_file_id == "tool-file-1"
