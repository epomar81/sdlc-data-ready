import json
import logging
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_previous_record_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs):
    record = _previous_record_factory(*args, **kwargs)
    value = _correlation_id.get()
    if value:
        record.correlation_id = value
    return record


logging.setLogRecordFactory(_record_factory)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = {"level": record.levelname.lower(), "message": record.getMessage()}
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id:
            fields["correlation_id"] = correlation_id
        return json.dumps(fields)


def configure_logging(correlation_id: str) -> None:
    _correlation_id.set(correlation_id)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = next(
        (item for item in root.handlers if getattr(item, "_intention_refiner_handler", False)),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler()
        handler._intention_refiner_handler = True
        root.addHandler(handler)
    handler.setFormatter(JsonLogFormatter())
