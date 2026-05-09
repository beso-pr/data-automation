"""Project-wide logging configuration (stdlib only).

Two handlers attached to the root logger:

* console — concise, level-coloured-ish format for humans.
* file (optional) — full timestamps + levels, rotating to keep history bounded.

Both handlers honour the same effective log level. The file handler is added
only if a path is supplied, so library users (and test runs) get console-only
behaviour by default.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

CONSOLE_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)-32s  %(message)s"
FILE_FORMAT = "%(asctime)s.%(msecs)03d  %(levelname)-7s  %(name)-40s  %(filename)s:%(lineno)d  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(
    level: str = "INFO",
    *,
    log_file: str | Path | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure the root logger.

    :param level: minimum level for both handlers.
    :param log_file: if given, also write logs to this file (rotating).
    :param max_bytes: rotate when the file exceeds this size.
    :param backup_count: keep this many rotated files.
    """
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())

    if not _CONFIGURED:
        root.handlers.clear()
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt="%H:%M:%S"))
        root.addHandler(console)
        for noisy in ("urllib3", "requests"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _CONFIGURED = True

    if log_file is not None:
        _attach_file_handler(root, Path(log_file), max_bytes, backup_count)


def _attach_file_handler(root: logging.Logger, path: Path, max_bytes: int, backup_count: int) -> None:
    # Don't double-attach if the same file is already wired up.
    target = path.resolve()
    for existing in root.handlers:
        if isinstance(existing, RotatingFileHandler) and Path(existing.baseFilename).resolve() == target:
            return

    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(handler)
    root.info("Logging to file: %s (rotate at %d bytes, keep %d backups)", path, max_bytes, backup_count)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def reset_for_tests() -> None:
    """Test helper — drop handlers + flag so a subsequent ``configure_logging`` re-runs."""
    global _CONFIGURED
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()
    _CONFIGURED = False
