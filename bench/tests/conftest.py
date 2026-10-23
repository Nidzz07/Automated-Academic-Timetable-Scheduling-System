"""Shared pytest configuration for the bench tests."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # pyproject's addopts deselects these; run them with -m slow
    config.addinivalue_line("markers", "slow: a full evaluation run (minutes)")
