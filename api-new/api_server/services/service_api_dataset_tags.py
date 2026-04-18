"""FastAPI-native dataset tag helpers for dataset-token `/v1` routes."""

from __future__ import annotations

import uuid
from typing import TypedDict

from sqlalchemy import func, select

from api_server.errors import bad_request, not_found
from api_server.models.app import Tag, TagBinding, TagType
from api_server.models.dataset import Dataset
from extensions.ext_database import db


class ServiceApiDatasetTagDict(TypedDict):
    id: str
    name: str
    type: str
    binding_count: int


class ServiceApiDatasetTagBindingStatusDict(TypedDict):
    data: list[dict[str, str]]
    total: int


class ServiceApiDatasetTagService:
    """List and mutate dataset tags without Flask login state."""

    @staticmethod
    async def _ensure_dataset_exists(*, tenant_id: str, dataset_id: str) -> None:
        async with db.session_context() as session:
            dataset = await session.scalar(
                select(Dataset).where(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id)
            )
        if dataset is None:
            raise not_found("dataset_not_found", "Dataset not found")

    @staticmethod
    async def _binding_count(*, tag_id: str) -> int:
        async with db.session_context() as session:
            count = await session.scalar(select(func.count(TagBinding.id)).where(TagBinding.tag_id == tag_id))
        return int(count or 0)

    @classmethod
    async def list_tags(cls, *, tenant_id: str) -> list[ServiceApiDatasetTagDict]:
        async with db.session_context() as session:
            rows = (
                await session.execute(
                    select(Tag.id, Tag.type, Tag.name, func.count(TagBinding.id).label("binding_count"))
                    .outerjoin(TagBinding, Tag.id == TagBinding.tag_id)
                    .where(Tag.type == TagType.KNOWLEDGE, Tag.tenant_id == tenant_id)
                    .group_by(Tag.id, Tag.type, Tag.name, Tag.created_at)
                    .order_by(Tag.created_at.desc())
                )
            ).all()

        return [
            {
                "id": row.id,
                "name": row.name,
                "type": row.type.value if hasattr(row.type, "value") else str(row.type),
                "binding_count": int(row.binding_count or 0),
            }
            for row in rows
        ]

    @classmethod
    async def create_tag(
        cls,
        *,
        tenant_id: str,
        owner_account_id: str,
        name: str,
    ) -> ServiceApiDatasetTagDict:
        async with db.session_context() as session:
            existing = await session.scalar(
                select(Tag).where(
                    Tag.name == name,
                    Tag.tenant_id == tenant_id,
                    Tag.type == TagType.KNOWLEDGE,
                )
            )
            if existing is not None:
                raise bad_request("tag_name_exists", "Tag name already exists")

            tag = Tag(
                id=str(uuid.uuid4()),
                name=name,
                type=TagType.KNOWLEDGE,
                created_by=owner_account_id,
                tenant_id=tenant_id,
            )
            async with session.begin():
                session.add(tag)

        return {"id": tag.id, "name": tag.name, "type": tag.type.value, "binding_count": 0}

    @classmethod
    async def update_tag(
        cls,
        *,
        tenant_id: str,
        tag_id: str,
        name: str,
    ) -> ServiceApiDatasetTagDict:
        async with db.session_context() as session:
            tag = await session.scalar(
                select(Tag).where(Tag.id == tag_id, Tag.tenant_id == tenant_id, Tag.type == TagType.KNOWLEDGE)
            )
            if tag is None:
                raise not_found("tag_not_found", "Tag not found")

            if name != tag.name:
                existing = await session.scalar(
                    select(Tag).where(
                        Tag.name == name,
                        Tag.tenant_id == tenant_id,
                        Tag.type == tag.type,
                        Tag.id != tag_id,
                    )
                )
                if existing is not None:
                    raise bad_request("tag_name_exists", "Tag name already exists")

            tag.name = name
            async with session.begin():
                session.add(tag)

        return {
            "id": tag.id,
            "name": tag.name,
            "type": tag.type.value,
            "binding_count": await cls._binding_count(tag_id=tag.id),
        }

    @classmethod
    async def delete_tag(cls, *, tenant_id: str, tag_id: str) -> None:
        async with db.session_context() as session:
            tag = await session.scalar(
                select(Tag).where(Tag.id == tag_id, Tag.tenant_id == tenant_id, Tag.type == TagType.KNOWLEDGE)
            )
            if tag is None:
                raise not_found("tag_not_found", "Tag not found")

            bindings = (
                await session.scalars(select(TagBinding).where(TagBinding.tag_id == tag_id))
            ).all()

            async with session.begin():
                for binding in bindings:
                    await session.delete(binding)
                await session.delete(tag)

    @classmethod
    async def bind_tags(
        cls,
        *,
        tenant_id: str,
        owner_account_id: str,
        tag_ids: list[str],
        dataset_id: str,
    ) -> None:
        await cls._ensure_dataset_exists(tenant_id=tenant_id, dataset_id=dataset_id)
        async with db.session_context() as session:
            for tag_id in tag_ids:
                existing = await session.scalar(
                    select(TagBinding).where(TagBinding.tag_id == tag_id, TagBinding.target_id == dataset_id)
                )
                if existing is not None:
                    continue
                session.add(
                    TagBinding(
                        id=str(uuid.uuid4()),
                        tag_id=tag_id,
                        target_id=dataset_id,
                        tenant_id=tenant_id,
                        created_by=owner_account_id,
                    )
                )
            async with session.begin():
                pass

    @classmethod
    async def unbind_tag(
        cls,
        *,
        tenant_id: str,
        tag_id: str,
        dataset_id: str,
    ) -> None:
        await cls._ensure_dataset_exists(tenant_id=tenant_id, dataset_id=dataset_id)
        async with db.session_context() as session:
            binding = await session.scalar(
                select(TagBinding).where(TagBinding.tag_id == tag_id, TagBinding.target_id == dataset_id)
            )
            if binding is not None:
                async with session.begin():
                    await session.delete(binding)

    @classmethod
    async def list_dataset_tags(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
    ) -> ServiceApiDatasetTagBindingStatusDict:
        await cls._ensure_dataset_exists(tenant_id=tenant_id, dataset_id=dataset_id)
        async with db.session_context() as session:
            tags = (
                await session.scalars(
                    select(Tag)
                    .join(TagBinding, Tag.id == TagBinding.tag_id)
                    .where(
                        TagBinding.target_id == dataset_id,
                        TagBinding.tenant_id == tenant_id,
                        Tag.tenant_id == tenant_id,
                        Tag.type == TagType.KNOWLEDGE,
                    )
                )
            ).all()

        return {"data": [{"id": tag.id, "name": tag.name} for tag in tags], "total": len(tags)}
