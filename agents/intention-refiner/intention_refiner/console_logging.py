import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_previous_record_factory = logging.getLogRecordFactory()


class _ApplicationLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith("intention_refiner") and record.levelno >= logging.INFO


def _record_factory(*args, **kwargs):
    record = _previous_record_factory(*args, **kwargs)
    value = _correlation_id.get()
    if value:
        record.correlation_id = value
    return record


logging.setLogRecordFactory(_record_factory)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        fields = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event": getattr(record, "event", record.getMessage()),
            "duration_ms": getattr(record, "duration_ms", None),
            "message": record.message,
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id:
            fields["correlation_id"] = correlation_id
        standard = logging.makeLogRecord({}).__dict__
        for key, value in record.__dict__.items():
            if key not in standard and key not in fields and key not in {"event", "duration_ms"}:
                fields[key] = value
        return json.dumps(fields, default=str)


def configure_logging(correlation_id: str) -> None:
    _correlation_id.set(correlation_id)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    log_filter = _ApplicationLogFilter()
    handler = next(
        (item for item in root.handlers if getattr(item, "_intention_refiner_handler", False)),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler()
        handler._intention_refiner_handler = True
        root.addHandler(handler)
    else:
        handler.stream = sys.stderr
    for configured_handler in root.handlers:
        configured_handler.setLevel(logging.INFO)
        configured_handler.setFormatter(JsonLogFormatter())
        if not any(isinstance(item, _ApplicationLogFilter) for item in configured_handler.filters):
            configured_handler.addFilter(log_filter)
