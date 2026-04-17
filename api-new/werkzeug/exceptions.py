"""Small subset of Werkzeug HTTP exceptions used by the migration code."""

from __future__ import annotations


class HTTPException(Exception):  # noqa: N818
    """Base HTTP exception carrying an HTTP status code."""

    code: int = 500
    description: str

    def __init__(self, description: str | None = None) -> None:
        self.description = description or self.__class__.__name__
        super().__init__(self.description)


class BadRequest(HTTPException):
    code = 400


class Unauthorized(HTTPException):
    code = 401


class Forbidden(HTTPException):
    code = 403


class NotFound(HTTPException):
    code = 404


class RequestEntityTooLarge(HTTPException):
    code = 413


class InternalServerError(HTTPException):
    code = 500
