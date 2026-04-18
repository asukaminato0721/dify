"""FastAPI-native conversation-variable helpers for `/v1` service API routes."""

from __future__ import annotations

import json
from typing import Any, TypedDict

from sqlalchemy import select

from api_server.errors import bad_request
from api_server.models.app import App, ConversationVariable, EndUser
from api_server.services.conversation_message import ConversationMessageService
from extensions.ext_database import db
from factories import variable_factory
from graphon.variables.exc import VariableError
from graphon.variables.types import SegmentType


class ServiceApiConversationVariableDict(TypedDict):
    id: str
    name: str
    value_type: str
    value: Any
    description: str | None
    created_at: int | None
    updated_at: int | None


class ServiceApiConversationVariablePaginationDict(TypedDict):
    limit: int
    has_more: bool
    data: list[ServiceApiConversationVariableDict]


class ServiceApiConversationVariableService:
    """List and update service-API conversation variables with async SQLAlchemy."""

    @staticmethod
    def _serialize_variable(
        *,
        row: ConversationVariable,
        mapping: dict[str, Any],
    ) -> ServiceApiConversationVariableDict:
        return {
            "id": str(mapping.get("id", row.id)),
            "name": str(mapping.get("name", "")),
            "value_type": str(mapping.get("value_type", "")),
            "value": mapping.get("value"),
            "description": mapping.get("description"),
            "created_at": int(row.created_at.timestamp()) if row.created_at is not None else None,
            "updated_at": int(row.updated_at.timestamp()) if row.updated_at is not None else None,
        }

    @classmethod
    async def list_variables(
        cls,
        *,
        app: App,
        conversation_id: str,
        end_user: EndUser,
        limit: int,
        last_id: str | None,
        variable_name: str | None,
    ) -> ServiceApiConversationVariablePaginationDict:
        await ConversationMessageService.list_messages(
            app_id=app.id,
            end_user=end_user,
            conversation_id=conversation_id,
            first_id=None,
            limit=1,
        )

        async with db.session_context() as session:
            rows = (
                await session.scalars(
                    select(ConversationVariable)
                    .where(
                        ConversationVariable.app_id == app.id,
                        ConversationVariable.conversation_id == conversation_id,
                    )
                    .order_by(ConversationVariable.created_at.asc())
                )
            ).all()

        parsed_rows: list[tuple[ConversationVariable, dict[str, Any]]] = []
        for row in rows:
            mapping = json.loads(row.data)
            if variable_name and variable_name.lower() not in str(mapping.get("name", "")).lower():
                continue
            parsed_rows.append((row, mapping))

        if last_id is not None:
            marker_index = next((index for index, (row, _) in enumerate(parsed_rows) if row.id == last_id), None)
            if marker_index is None:
                raise bad_request("conversation_variable_not_exists", "Conversation Variable Not Exists.")
            parsed_rows = parsed_rows[marker_index + 1 :]

        has_more = len(parsed_rows) > limit
        page_rows = parsed_rows[:limit]
        return {
            "limit": limit,
            "has_more": has_more,
            "data": [cls._serialize_variable(row=row, mapping=mapping) for row, mapping in page_rows],
        }

    @classmethod
    async def update_variable(
        cls,
        *,
        app: App,
        conversation_id: str,
        variable_id: str,
        end_user: EndUser,
        value: Any,
    ) -> ServiceApiConversationVariableDict:
        await ConversationMessageService.list_messages(
            app_id=app.id,
            end_user=end_user,
            conversation_id=conversation_id,
            first_id=None,
            limit=1,
        )

        async with db.session_context() as session:
            row = await session.scalar(
                select(ConversationVariable).where(
                    ConversationVariable.app_id == app.id,
                    ConversationVariable.conversation_id == conversation_id,
                    ConversationVariable.id == variable_id,
                )
            )
            if row is None:
                raise bad_request("conversation_variable_not_exists", "Conversation Variable Not Exists.")

            mapping = json.loads(row.data)
            current_variable = variable_factory.build_conversation_variable_from_mapping(mapping)

            expected_type = SegmentType(current_variable.value_type)
            if expected_type == SegmentType.INTEGER:
                expected_type = SegmentType.NUMBER

            if not expected_type.is_valid(value):
                inferred_type = SegmentType.infer_segment_type(value)
                inferred_value = inferred_type.value if inferred_type is not None else "unknown"
                raise bad_request(
                    "conversation_variable_type_mismatch",
                    (
                        f"Type mismatch: variable '{current_variable.name}' expects {expected_type.value}, "
                        f"but got {inferred_value} type"
                    ),
                )

            updated_mapping = {
                "id": current_variable.id,
                "name": current_variable.name,
                "description": current_variable.description,
                "value_type": current_variable.value_type,
                "value": value,
                "selector": current_variable.selector,
            }

            try:
                updated_variable = variable_factory.build_conversation_variable_from_mapping(updated_mapping)
            except VariableError as exc:
                raise bad_request("conversation_variable_invalid", str(exc)) from exc

            row.data = updated_variable.model_dump_json()
            async with session.begin():
                session.add(row)
            await session.refresh(row)

        return cls._serialize_variable(row=row, mapping=updated_mapping)
