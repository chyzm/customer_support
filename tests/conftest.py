import os
from pathlib import Path
from shutil import copyfile

# Set safe defaults before importing the application. Individual API tests get
# their own migrated database path from the fixture below.
os.environ["JEV_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./unused-test.db"
os.environ["API_AUTH_ENABLED"] = "false"
os.environ["RATE_LIMIT_REQUESTS"] = "1000"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@pytest.fixture(scope="session")
def migrated_database(tmp_path_factory) -> Path:
    """Apply the real migration chain once to create a reusable clean template."""
    path = tmp_path_factory.mktemp("database-template") / "template.db"
    config = Config("alembic.ini")
    config.attributes["database_url"] = _database_url(path)
    command.upgrade(config, "head")
    return path


@pytest.fixture
def client(tmp_path, monkeypatch, migrated_database):
    """Fresh app and independently migrated SQLite database for every API test."""
    database = tmp_path / "test.db"
    copyfile(migrated_database, database)
    monkeypatch.setenv("DATABASE_URL", _database_url(database))
    get_settings.cache_clear()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_settings.cache_clear()
