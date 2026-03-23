import logging
import sys


LOG_FORMAT = "%(levelname)-7s | %(name)s | %(message)s"

_WERKZEUG_NOISE = ("bad http/0.9 request", "bad request syntax", "bad request version")


class _WerkzeugNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage().lower()
        return not any(phrase in msg for phrase in _WERKZEUG_NOISE)


def configure_logging(level: int = logging.INFO) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.handlers:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(handler)

    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.ERROR)
    werkzeug_logger.addFilter(_WerkzeugNoiseFilter())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
