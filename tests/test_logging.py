import json
import logging

import pytest

from app.config.logging import (
    NO_REQUEST_ID,
    JsonFormatter,
    RequestIdFilter,
    set_request_id,
    setup_logging,
)


@pytest.fixture(autouse=True)
def reset_request_id() -> None:
    set_request_id(NO_REQUEST_ID)


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="extraction finished iteration=%s",
        args=(2,),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


@pytest.mark.parametrize("level", ["DEBUG", "WARNING"])
def test_log_level_is_injectable(level: str) -> None:
    setup_logging(level=level)

    assert logging.getLogger("app").level == getattr(logging, level)


def test_setup_logging_selects_the_json_formatter() -> None:
    setup_logging(level="INFO", log_format="json")
    handler = logging.getLogger("app").handlers[0]

    assert isinstance(handler.formatter, JsonFormatter)


def test_json_formatter_emits_one_object_per_record() -> None:
    payload = json.loads(JsonFormatter().format(_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "extraction finished iteration=2"
    assert payload["request_id"] == NO_REQUEST_ID


def test_json_formatter_promotes_extra_fields() -> None:
    payload = json.loads(JsonFormatter().format(_record(iteration=2, approved=True)))

    assert payload["iteration"] == 2
    assert payload["approved"] is True


def test_json_formatter_drops_uvicorn_ansi_duplicate() -> None:
    payload = json.loads(JsonFormatter().format(_record(color_message="\x1b[36m%s")))

    assert "color_message" not in payload


def test_request_id_filter_stamps_the_current_context() -> None:
    set_request_id("abc123")
    record = _record()

    assert RequestIdFilter().filter(record) is True
    assert json.loads(JsonFormatter().format(record))["request_id"] == "abc123"
