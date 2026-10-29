import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("wayfare")


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


def NotFound(message: str = "We couldn't find that.") -> AppError:
    return AppError("not_found", message, 404)


def Forbidden(message: str = "You're not part of this trip.") -> AppError:
    return AppError("forbidden", message, 403)


def Unauthorized(message: str = "Please sign in again.") -> AppError:
    return AppError("unauthorized", message, 401)


def _envelope(code: str, message: str, status: int, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _envelope(exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "issue": e["msg"]}
            for e in exc.errors()
        ]
        return _envelope("invalid_input", "Some of the details look off. Please check and try again.", 422, fields)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error")  # stack trace goes to logs only
        return _envelope("server_error", "Something went wrong on our side. Please try again in a moment.", 500)
