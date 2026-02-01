"""OpenAPI compatibility helpers built on Flask + flask_openapi3.

This module provides a minimal subset of Flask-RESTX features used in this
codebase (Resource, Namespace, fields, marshal helpers, and request parsing),
implemented without the flask_restx dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import wraps
from http import HTTPStatus
from typing import Any, TypeVar, cast

from flask import Blueprint, Flask, Response, request
from flask.views import MethodView
from flask_openapi3 import APIBlueprint
from werkzeug.exceptions import BadRequest, HTTPException, MethodNotAllowed

T = TypeVar("T")


class Field:
    attribute: str | Callable[[Any], Any] | None
    default: Any
    allow_null: bool

    def __init__(
        self,
        *,
        attribute: str | Callable[[Any], Any] | None = None,
        default: Any = None,
        allow_null: bool = False,
        **_: Any,
    ) -> None:
        self.attribute = attribute
        self.default = default
        self.allow_null = allow_null

    def format(self, value: Any) -> Any:
        return value

    def output(self, key: str, obj: Any) -> Any:
        value = _resolve_attribute(obj, key, self.attribute)
        if value is None:
            if self.default is not None:
                return self.default
            if self.allow_null:
                return None
        return self.format(value)


class Raw(Field):
    pass


class String(Field):
    def format(self, value: Any) -> Any:
        if value is None:
            return None
        return str(value)


class Integer(Field):
    def format(self, value: Any) -> Any:
        if value is None:
            return None
        return int(value)


class Float(Field):
    def format(self, value: Any) -> Any:
        if value is None:
            return None
        return float(value)


class Boolean(Field):
    def format(self, value: Any) -> Any:
        if value is None:
            return None
        return bool(value)


class Nested(Field):
    model: Mapping[str, Any] | None

    def __init__(
        self,
        model: Mapping[str, Any] | None = None,
        *,
        attribute: str | Callable[[Any], Any] | None = None,
        allow_null: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(attribute=attribute, allow_null=allow_null, **kwargs)
        self.model = model

    def output(self, key: str, obj: Any) -> Any:
        value = _resolve_attribute(obj, key, self.attribute)
        if value is None:
            return None if self.allow_null else None
        return marshal(value, self.model or {})


class List(Field):
    container: Field

    def __init__(
        self,
        container: Field | type[Field],
        *,
        attribute: str | Callable[[Any], Any] | None = None,
        allow_null: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(attribute=attribute, allow_null=allow_null, **kwargs)
        self.container = _ensure_field(container)

    def output(self, key: str, obj: Any) -> Any:
        value = _resolve_attribute(obj, key, self.attribute)
        if value is None:
            return None if self.allow_null else []
        if isinstance(value, Mapping):
            items: Iterable[Any] = value.values()
        elif isinstance(value, (list, tuple, set)):
            items = value
        else:
            items = [value]
        return [_marshal_list_item(item, self.container) for item in items]


class _FieldsModule:
    Raw = Raw
    String = String
    Integer = Integer
    Float = Float
    Boolean = Boolean
    Nested = Nested
    List = List


fields = _FieldsModule()


class Model(dict):
    name: str

    def __init__(self, name: str, field_def: Mapping[str, Any]) -> None:
        super().__init__(field_def)
        self.name = name


class Resource(MethodView):
    method_decorators: list[Callable[..., Any]] | Mapping[str, list[Callable[..., Any]]] = []

    def dispatch_request(self, *args: Any, **kwargs: Any) -> Any:
        method_name = request.method.lower()
        handler = getattr(self, method_name, None)
        if handler is None:
            raise MethodNotAllowed(valid_methods=_available_methods(self.__class__))
        decorators = self._get_decorators(method_name)
        for decorator in decorators:
            handler = decorator(handler)
        return handler(*args, **kwargs)

    def _get_decorators(self, method_name: str) -> list[Callable[..., Any]]:
        decorators = self.method_decorators
        if isinstance(decorators, Mapping):
            return decorators.get(method_name, [])
        return list(decorators or [])


class Namespace:
    name: str
    description: str | None
    path: str
    models: dict[str, Any]
    _routes: list[tuple[str, type[Resource], dict[str, Any]]]

    def __init__(self, name: str, description: str | None = None, path: str = "") -> None:
        self.name = name
        self.description = description
        self.path = path
        self.models = {}
        self._routes = []

    @property
    def payload(self) -> Any:
        return request.get_json(silent=True)

    def model(self, name: str, field_def: Mapping[str, Any]) -> Mapping[str, Any]:
        model = Model(name=name, field_def=field_def)
        self.models[name] = model
        return model

    def route(self, path: str, **options: Any):
        def decorator(resource_cls: type[Resource]):
            self._routes.append((path, resource_cls, options))
            return resource_cls

        return decorator

    def add_resource(self, resource_cls: type[Resource], path: str, **options: Any) -> None:
        self._routes.append((path, resource_cls, options))

    def register(self, blueprint: Blueprint | Flask) -> None:
        for index, (path, resource_cls, options) in enumerate(self._routes):
            endpoint = f"{self.name}.{resource_cls.__name__}.{index}"
            full_path = _join_path(self.path, path)
            register_resource(blueprint, full_path, resource_cls, endpoint=endpoint, **options)

    def doc(self, *_: Any, **__: Any):
        def decorator(obj: T) -> T:
            return obj

        return decorator

    def response(self, *_: Any, **__: Any):
        def decorator(obj: T) -> T:
            return obj

        return decorator

    def expect(self, *_: Any, **__: Any):
        def decorator(obj: T) -> T:
            return obj

        return decorator

    def marshal_with(self, field_def: Mapping[str, Any], code: int | None = None, **kwargs: Any):
        return marshal_with(field_def, code=code, **kwargs)


class RequestParser:
    def __init__(self) -> None:
        self._args: list[_RequestArg] = []

    def add_argument(
        self,
        name: str,
        *,
        type: Callable[[Any], Any] | None = None,
        required: bool = False,
        default: Any = None,
        location: str = "json",
        nullable: bool = True,
        **_: Any,
    ) -> None:
        self._args.append(
            _RequestArg(
                name=name,
                type=type,
                required=required,
                default=default,
                location=location,
                nullable=nullable,
            )
        )

    def parse_args(self) -> dict[str, Any]:
        payload = request.get_json(silent=True) or {}
        query = request.args.to_dict(flat=True)
        form = request.form.to_dict(flat=True)

        data: dict[str, Any] = {}
        for arg in self._args:
            source = payload if arg.location == "json" else query if arg.location == "args" else form
            raw_value = source.get(arg.name, None)
            if raw_value is None:
                if arg.required:
                    raise BadRequest(f"{arg.name} is required")
                data[arg.name] = arg.default
                continue
            if raw_value is None and not arg.nullable:
                raise BadRequest(f"{arg.name} cannot be null")
            if arg.type is not None:
                try:
                    raw_value = arg.type(raw_value)
                except (TypeError, ValueError) as exc:
                    raise BadRequest(str(exc)) from exc
            data[arg.name] = raw_value
        return data


@dataclass(frozen=True)
class _RequestArg:
    name: str
    type: Callable[[Any], Any] | None
    required: bool
    default: Any
    location: str
    nullable: bool


class _ReqParseModule:
    RequestParser = RequestParser


reqparse = _ReqParseModule()


def abort(code: int | HTTPStatus, message: str | None = None, **kwargs: Any) -> None:
    status_code = int(code)
    try:
        from werkzeug.exceptions import default_exceptions

        exc_class = default_exceptions.get(status_code, HTTPException)
    except Exception:
        exc_class = HTTPException
    error = exc_class(description=message)
    if getattr(error, "code", None) is None:
        error.code = status_code
    data = dict(kwargs)
    if message is not None:
        data.setdefault("message", message)
    error.data = data
    raise error


def marshal(data: Any, fields_def: Mapping[str, Any] | None, skip_none: bool = False) -> Any:
    if fields_def is None:
        return data
    fields_def = cast(Mapping[str, Any], fields_def)

    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray, Mapping)):
        return [marshal(item, fields_def, skip_none=skip_none) for item in data]

    if _is_pydantic_model(data):
        data = data.model_dump(mode="json")

    result: dict[str, Any] = {}
    for key, field in fields_def.items():
        field_instance = _ensure_field(field)
        value = _marshal_item(data, field_instance, key=key)
        if skip_none and value is None:
            continue
        result[key] = value
    return result


def marshal_with(fields_def: Mapping[str, Any], code: int | None = None, **kwargs: Any):
    skip_none = bool(kwargs.get("skip_none", False))

    def decorator(func: Callable[..., Any]):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            result = func(*args, **kwargs)
            if isinstance(result, Response):
                return result
            data, status, headers = _unwrap_response(result)
            marshalled = marshal(data, fields_def, skip_none=skip_none)
            if status is None and code is not None and code != 200:
                status = code
            if headers is not None and status is not None:
                return marshalled, status, headers
            if status is not None:
                return marshalled, status
            return marshalled

        return wrapper

    return decorator


def register_resource(
    blueprint: Blueprint | Flask,
    path: str,
    resource_cls: type[Resource],
    *,
    endpoint: str | None = None,
    **options: Any,
) -> None:
    methods = _available_methods(resource_cls)
    view_func = resource_cls.as_view(endpoint or resource_cls.__name__)
    blueprint.add_url_rule(path, view_func=view_func, methods=methods, **options)


def _unwrap_response(result: Any) -> tuple[Any, int | None, Mapping[str, Any] | None]:
    if isinstance(result, tuple):
        if len(result) == 3:
            return result[0], _status_code(result[1]), cast(Mapping[str, Any], result[2])
        if len(result) == 2:
            if isinstance(result[1], Mapping):
                return result[0], None, cast(Mapping[str, Any], result[1])
            return result[0], _status_code(result[1]), None
    return result, None, None


def _status_code(value: Any) -> int:
    if isinstance(value, HTTPStatus):
        return int(value)
    if isinstance(value, int):
        return value
    return int(value)


def _available_methods(resource_cls: type[Resource]) -> list[str]:
    methods = []
    for method_name in ("get", "post", "put", "patch", "delete", "options", "head"):
        if callable(getattr(resource_cls, method_name, None)):
            methods.append(method_name.upper())
    return methods


def _join_path(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if prefix.endswith("/") and path.startswith("/"):
        return prefix[:-1] + path
    if not prefix.endswith("/") and not path.startswith("/"):
        return f"{prefix}/{path}"
    return prefix + path


def _ensure_field(field: Field | type[Field] | Mapping[str, Any]) -> Field:
    if isinstance(field, Field):
        return field
    if isinstance(field, type) and issubclass(field, Field):
        return field()
    return Nested(field)


def _marshal_item(obj: Any, field: Field, key: str | None = None) -> Any:
    if key is None:
        return field.format(obj)
    return field.output(key, obj)


def _marshal_list_item(obj: Any, field: Field) -> Any:
    if isinstance(field, Nested):
        return marshal(obj, field.model or {})
    return field.format(obj)


def _resolve_attribute(obj: Any, key: str, attribute: str | Callable[[Any], Any] | None) -> Any:
    if callable(attribute):
        return attribute(obj)
    attr_name = attribute or key
    if isinstance(obj, Mapping):
        return obj.get(attr_name)
    return getattr(obj, attr_name, None)


def _is_pydantic_model(value: Any) -> bool:
    return hasattr(value, "model_dump") and callable(value.model_dump)


__all__ = [
    "APIBlueprint",
    "HTTPStatus",
    "Namespace",
    "Resource",
    "abort",
    "fields",
    "marshal",
    "marshal_with",
    "register_resource",
    "reqparse",
]
