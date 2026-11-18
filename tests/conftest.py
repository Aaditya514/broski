"""Shared pytest fixtures for broski test suite."""

import os
from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def clean_env() -> Generator[None, None, None]:
    """Ensure clean test environment by resetting relevant env variables."""
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)
