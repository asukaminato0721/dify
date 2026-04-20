from __future__ import annotations

from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker

from services.conversation_variable_updater import ConversationVariableUpdater


def test_update_uses_async_sessionmaker_path() -> None:
    session_maker = async_sessionmaker()
    updater = ConversationVariableUpdater(session_maker)
    variable = type("VariableStub", (), {"id": "var-1", "model_dump_json": lambda self: '{"value":1}'})()

    with patch.object(updater, "_aupdate", new=AsyncMock()) as aupdate_mock:
        updater.update("conversation-1", variable)

    aupdate_mock.assert_awaited_once()
