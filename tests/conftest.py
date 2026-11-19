import os

# Must be set before the app reads settings. Environment variables win over .env,
# so tests never touch the real triage.db and never need a TypeSafe key.
os.environ["JEV_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    """A fresh app and a fresh empty in-memory database for every test."""
    with TestClient(app) as c:  # entering the `with` block runs the lifespan startup
        yield c
    app.dependency_overrides.clear()
