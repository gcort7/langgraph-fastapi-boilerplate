import logging
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import new_request_id, set_request_id

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware:
    """Bind a request id to the log context and log one line per request.

    Written as pure ASGI rather than on `BaseHTTPMiddleware`, which buffers
    streaming responses and swallows background-task exceptions.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get(REQUEST_ID_HEADER) or new_request_id()
        set_request_id(request_id)

        method = scope["method"]
        path = scope["path"]
        started = time.perf_counter()
        status_code = 0

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception(
                "Request failed method=%s path=%s duration_ms=%.1f",
                method,
                path,
                (time.perf_counter() - started) * 1000,
            )
            raise

        logger.info(
            "Request completed method=%s path=%s status=%s duration_ms=%.1f",
            method,
            path,
            status_code,
            (time.perf_counter() - started) * 1000,
        )
