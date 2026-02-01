"""Helpers for registering Pydantic models with OpenAPI namespaces."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, TypeAdapter

from controllers.console import console_ns
from libs.openapi import Namespace

DEFAULT_REF_TEMPLATE_SWAGGER_2_0 = "#/definitions/{model}"


def get_or_create_model(model_name: str, field_def: dict[str, Any]):
    existing = console_ns.models.get(model_name)
    if existing is None:
        existing = console_ns.model(model_name, field_def)
    return existing


def register_schema_model(namespace: Namespace, model: type[BaseModel]) -> None:
    namespace.models[model.__name__] = model


def register_schema_models(namespace: Namespace, *models: type[BaseModel]) -> None:
    for model in models:
        register_schema_model(namespace, model)


def register_enum_models(namespace: Namespace, *enums: type[StrEnum]) -> None:
    for enum in enums:
        TypeAdapter(enum)
        namespace.models[enum.__name__] = enum


__all__ = [
    "DEFAULT_REF_TEMPLATE_SWAGGER_2_0",
    "get_or_create_model",
    "register_enum_models",
    "register_schema_model",
    "register_schema_models",
]
