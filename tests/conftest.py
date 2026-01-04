"""Pytest configuration fixtures."""

import logging

import pytest


@pytest.fixture(autouse=True)
def silence_httpx_logs() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
