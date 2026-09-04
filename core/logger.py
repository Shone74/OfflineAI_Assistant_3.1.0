"""Centralised logging system for the Offline AI Assistant.

Provides a single configured logger that writes both to the console
and to rotating log files in ``logs/``:

* ``logs/assistant.log``  — general application log (INFO+)
* ``logs/errors.log``     — error-only log (ERROR+)
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from core.paths import LOGS_DIR

_LOGS_DIR_INITIALIZED = False


def _ensure_logs_dir() -> None:
    global _LOGS_DIR_INITIALIZED
    if _LOGS_DIR_INITIALIZED:
        return
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _LOGS_DIR_INITIALIZED = True


def get_logger(name: str = "offlineai") -> logging.Logger:
    """Return a configured logger.

    Called multiple times is safe — handlers are only added once.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    _ensure_logs_dir()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    main_handler = TimedRotatingFileHandler(
        LOGS_DIR / "assistant.log",
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    main_handler.setLevel(logging.DEBUG)
    main_handler.setFormatter(formatter)
    logger.addHandler(main_handler)

    error_handler = TimedRotatingFileHandler(
        LOGS_DIR / "errors.log",
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger


def get_logger_for_module(module: str) -> logging.Logger:
    """Return a child logger for a specific module (``offlineai.<module>``)."""
    return logging.getLogger(f"offlineai.{module}")


_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def apply_log_level(level: str) -> None:
    """Apply a logging level string to the *offlineai* logger's handlers at runtime.

    Updates the console and main file handler levels. The dedicated error
    file handler (``errors.log``) remains permanently at ``ERROR`` level
    so that error-only logging is preserved regardless of the selected level.

    Supported levels: ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``,
    ``CRITICAL``.  Invalid or unknown values fall back to ``INFO``.
    """
    numeric_level = _LEVEL_MAP.get(level.upper(), logging.INFO)

    lg = logging.getLogger("offlineai")
    if not lg.handlers:
        lg = get_logger("offlineai")

    for handler in lg.handlers:
        if hasattr(handler, "baseFilename") and "errors.log" in handler.baseFilename:
            continue
        handler.setLevel(numeric_level)
