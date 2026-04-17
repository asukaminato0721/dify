from __future__ import annotations

import enum
import uuid
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import CHAR, TEXT, VARCHAR, LargeBinary, MetaData, TypeDecorator
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
from sqlalchemy.sql.type_api import TypeEngine

POSTGRES_INDEXES_NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}

metadata = MetaData(naming_convention=POSTGRES_INDEXES_NAMING_CONVENTION)


class Base(AsyncAttrs, DeclarativeBase):
    metadata = metadata


class TypeBase(MappedAsDataclass, AsyncAttrs, DeclarativeBase):
    metadata = metadata


class StringUUID(TypeDecorator[uuid.UUID | str | None]):
    impl = CHAR
    cache_ok = True

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return value
        if dialect.name in ["postgresql", "mysql"]:
            return str(value)
        if isinstance(value, uuid.UUID):
            return value.hex
        return value

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID())
        return dialect.type_descriptor(CHAR(36))

    def process_result_value(self, value: uuid.UUID | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return value
        return str(value)


class LongText(TypeDecorator[str | None]):
    impl = TEXT
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return value

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TEXT())
        if dialect.name == "mysql":
            return dialect.type_descriptor(LONGTEXT())
        return dialect.type_descriptor(TEXT())

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return value


class BinaryData(TypeDecorator[bytes | None]):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: bytes | None, dialect: Dialect) -> bytes | None:
        return value

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(BYTEA())
        if dialect.name == "mysql":
            return dialect.type_descriptor(LONGBLOB())
        return dialect.type_descriptor(LargeBinary())

    def process_result_value(self, value: bytes | None, dialect: Dialect) -> bytes | None:
        return value


class AdjustedJSON(TypeDecorator[dict | list | None]):
    impl = sa.JSON
    cache_ok = True

    def __init__(self, astext_type: Any = None):
        self.astext_type = astext_type
        super().__init__()

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            if self.astext_type:
                return dialect.type_descriptor(JSONB(astext_type=self.astext_type))
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(sa.JSON())

    def process_bind_param(
        self, value: dict[str, Any] | list[Any] | None, dialect: Dialect
    ) -> dict[str, Any] | list[Any] | None:
        return value

    def process_result_value(
        self, value: dict[str, Any] | list[Any] | None, dialect: Dialect
    ) -> dict[str, Any] | list[Any] | None:
        return value


class EnumText[T: enum.StrEnum](TypeDecorator[T | None]):
    impl = VARCHAR
    cache_ok = True

    _length: int
    _enum_class: type[T]

    def __init__(self, enum_class: type[T], length: int | None = None):
        self._enum_class = enum_class
        max_enum_value_len = max(len(e.value) for e in enum_class)
        self._length = max_enum_value_len if length is None else max(length, max_enum_value_len)

    def process_bind_param(self, value: T | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return value
        if isinstance(value, self._enum_class):
            return value.value
        self._enum_class(value)
        return value

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        return dialect.type_descriptor(VARCHAR(self._length))

    def process_result_value(self, value: str | None, dialect: Dialect) -> T | None:
        if value is None or value == "":
            return None
        try:
            return self._enum_class(value)
        except ValueError:
            value_of = getattr(self._enum_class, "value_of", None)
            if callable(value_of):
                return cast(T, value_of(value))
            raise
