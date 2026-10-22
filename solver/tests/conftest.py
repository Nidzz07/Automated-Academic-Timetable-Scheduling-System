"""Shared pytest configuration for the solver tests."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Deselect with -m "not slow"; nothing is skipped by default.
    config.addinivalue_line("markers", "slow: runs longer than 60 s (none since S12g)")
