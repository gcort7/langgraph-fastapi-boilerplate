"""One error shape for every failure, so clients only parse one thing."""

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_request_id

logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    error: str = Field(description="Stable machine-readable error code.")
    detail: str = Field(description="Human-readable explanation.")
    request_id: str = Field(description="Correlates with logs and traces.")


class WorkflowError(Exception):
    """A workflow failed for reasons outside the caller's control."""

    def __init__(self, workflow: str) -> None:
        super().__init__(f"Workflow {workflow!r} failed")
        self.workflow = workflow


def _envelope(status_code: int, error: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error, detail=detail, request_id=get_request_id())
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def on_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _envelope(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_request",
            "; ".join(
                f"{'.'.join(str(part) for part in err['loc'][1:])}: {err['msg']}"
                for err in exc.errors()
            ),
        )

    @app.exception_handler(WorkflowError)
    async def on_workflow_error(request: Request, exc: WorkflowError) -> JSONResponse:
        return _envelope(
            status.HTTP_502_BAD_GATEWAY,
            "workflow_failed",
            f"The {exc.workflow} workflow could not complete.",
        )

    @app.exception_handler(HTTPException)
    async def on_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return _envelope(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def on_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals: the request id is how an operator finds the trace.
        logger.exception("Unhandled error path=%s", request.url.path)
        return _envelope(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred.",
        )
