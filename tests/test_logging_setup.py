"""Tests for the logging setup helpers."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from etl_pipeline.logging_setup import configure_logging, reset_for_tests


@pytest.fixture(autouse=True)
def _clean_logging() -> None:
    reset_for_tests()
    yield
    reset_for_tests()


def test_console_only_when_no_log_file() -> None:
    configure_logging("INFO")
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.StreamHandler) for h in handlers)
    assert not any(isinstance(h, RotatingFileHandler) for h in handlers)


def test_attaches_rotating_file_handler(tmp_path: Path) -> None:
    log_path = tmp_path / "etl.log"
    configure_logging("INFO", log_file=log_path, max_bytes=1024, backup_count=2)
    handlers = logging.getLogger().handlers
    file_handlers = [h for h in handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    handler = file_handlers[0]
    assert Path(handler.baseFilename).resolve() == log_path.resolve()
    assert handler.maxBytes == 1024
    assert handler.backupCount == 2


def test_file_handler_actually_writes(tmp_path: Path) -> None:
    log_path = tmp_path / "etl.log"
    configure_logging("DEBUG", log_file=log_path)
    logging.getLogger("test").info("hello world")

    for h in logging.getLogger().handlers:
        h.flush()
    text = log_path.read_text(encoding="utf-8")
    assert "hello world" in text
    assert "INFO" in text


def test_double_attach_is_idempotent(tmp_path: Path) -> None:
    log_path = tmp_path / "etl.log"
    configure_logging("INFO", log_file=log_path)
    configure_logging("INFO", log_file=log_path)  # second call shouldn't add another handler
    file_handlers = [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
