import json
import logging
from contextvars import ContextVar
from logging.config import dictConfig
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml
from opentelemetry import trace

CONFIG_FILE = Path(__file__).resolve().parent / "logging.yaml"

NO_REQUEST_ID = "-"

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)

# Attributes always present on a LogRecord. Anything else was passed by the
# caller through `extra=` and belongs in the structured output.
_RESERVED_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {
    "asctime",
    "message",
    "taskName",
    "request_id",
    "color_message",  # uvicorn's ANSI duplicate of the message
}


def new_request_id() -> str:
    return uuid4().hex


def set_request_id(request_id: str) -> None:
    """Bind a request id to the current context so every log line carries it."""
    _request_id.set(request_id)


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Attach the current context's request id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """Render records as single-line JSON so log aggregators can query fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", NO_REQUEST_ID),
        }

        # Present only inside a sampled span; lets a log line be opened as a trace.
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _RESERVED_RECORD_ATTRS
            }
        )
        return json.dumps(payload, default=str)


def setup_logging(
    level: str = "INFO",
    log_format: Literal["text", "json"] = "text",
) -> None:
    """Configure logging from logging.yaml, overriding level and formatter."""
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))

    config["loggers"]["app"]["level"] = level.upper()
    config["handlers"]["console"]["formatter"] = log_format

    dictConfig(config)
