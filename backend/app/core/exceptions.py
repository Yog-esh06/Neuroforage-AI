"""Domain exceptions and their HTTP mapping."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class NeuroForgeError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(NeuroForgeError):
    status_code = 404
    code = "not_found"


class ValidationFailed(NeuroForgeError):
    status_code = 422
    code = "validation_failed"


class UnsupportedFileError(NeuroForgeError):
    status_code = 415
    code = "unsupported_file"


class FileTooLargeError(NeuroForgeError):
    status_code = 413
    code = "file_too_large"


class AuthError(NeuroForgeError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(NeuroForgeError):
    status_code = 403
    code = "forbidden"


class ConflictError(NeuroForgeError):
    status_code = 409
    code = "conflict"


class IngestionError(NeuroForgeError):
    status_code = 422
    code = "ingestion_failed"


class ProviderError(NeuroForgeError):
    status_code = 502
    code = "llm_provider_error"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NeuroForgeError)
    async def _domain(_: Request, exc: NeuroForgeError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error", "details": {}}},
        )
