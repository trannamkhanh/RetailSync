"""Every error response is {"outcome": ..., "code": ..., "message": ...}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)

_HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, outcome: str = "REJECTED"):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.outcome = outcome


def _body(status: int, outcome: str, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"outcome": outcome, "code": code, "message": message})


def _field_name(error: dict) -> str:
    if error["type"] == "json_invalid":
        return "body"
    location = error["loc"]
    return ".".join(str(part) for part in location[1:] or location)


async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
    return _body(exc.status, exc.outcome, exc.code, exc.message)


async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    error = exc.errors()[0]
    message = f"Invalid field '{_field_name(error)}': {error['msg']}"
    return _body(422, "REJECTED", "VALIDATION_ERROR", message)


async def _handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    return _body(exc.status_code, "REJECTED", code, str(exc.detail))


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return _body(503, "ERROR", "SERVICE_UNAVAILABLE", "Service unavailable. Try again later.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
