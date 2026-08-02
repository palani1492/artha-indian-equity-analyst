from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_MODE", "demo")
os.environ.setdefault("APP_ENV", "test")

from app.api import create_app
from app.container import build_container
from app.settings import Settings


@pytest.fixture
def settings() -> Settings:
    # Keep the unauthenticated-path tests deterministic even when CI provides
    # DEMO_USER_ID for other demo-mode fixtures.
    return Settings(auth_mode="demo", app_env="test", demo_user_id=None)


@pytest.fixture
def container(settings: Settings):
    return build_container(settings)


@pytest.fixture
def client(container) -> TestClient:
    app = create_app(container=container)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-User-ID": "investor@example.com"}
