"""Configuration tests do not need the parent suite's autouse database fixtures."""

import pytest


@pytest.fixture(scope="session")
def fastapi_app() -> None:
    """Disable authenticated app setup for configuration-only tests."""


@pytest.fixture(scope="session")
def fastapi_app_not_authenticated() -> None:
    """Disable unauthenticated app setup for configuration-only tests."""


@pytest.fixture
def db_session() -> None:
    """Disable transaction setup for configuration-only tests."""
