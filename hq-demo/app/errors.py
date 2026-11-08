"""Errors that map to the DS-04 Error body."""

from fastapi import Request
from fastapi.responses import JSONResponse


class HqError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class NackError(HqError):
    """A batch-level refusal, answered with the DS-04 Nack body."""

    def __init__(self, status_code: int, code: str, message: str,
                 batch_id: str | None = None) -> None:
        super().__init__(status_code, code, message)
        self.batch_id = batch_id


async def hq_error_handler(_: Request, error: HqError) -> JSONResponse:
    if isinstance(error, NackError):
        return JSONResponse(
            status_code=error.status_code,
            content={"status": "NACK", "batch_id": error.batch_id,
                     "code": error.code, "message": error.message},
        )
    return JSONResponse(
        status_code=error.status_code,
        content={"outcome": "REJECTED", "code": error.code, "message": error.message},
    )
