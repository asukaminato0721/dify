from __future__ import annotations


class ApiError(Exception):
    """Framework-native API error used by the FastAPI port."""

    status_code: int
    code: str
    message: str

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def bad_request(code: str, message: str) -> ApiError:
    return ApiError(status_code=400, code=code, message=message)


def unauthorized(code: str, message: str) -> ApiError:
    return ApiError(status_code=401, code=code, message=message)


def forbidden(code: str, message: str) -> ApiError:
    return ApiError(status_code=403, code=code, message=message)


def not_found(code: str, message: str) -> ApiError:
    return ApiError(status_code=404, code=code, message=message)


def service_unavailable(code: str, message: str) -> ApiError:
    return ApiError(status_code=503, code=code, message=message)
