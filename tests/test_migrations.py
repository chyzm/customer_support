import sqlite3

from alembic import command
from alembic.config import Config

from app.db.readiness import check_database
from app.db.session import create_engine
from app.db.version import EXPECTED_DB_REVISION


def alembic_config(path) -> Config:
    config = Config("alembic.ini")
    config.attributes["database_url"] = f"sqlite:///{path.as_posix()}"
    return config


def test_initial_migration_upgrade_check_and_downgrade(tmp_path):
    database = tmp_path / "migration.db"
    config = alembic_config(database)

    command.upgrade(config, "head")
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert version == EXPECTED_DB_REVISION
    assert {"tickets", "evaluations", "decisions", "reviews"} <= tables

    # Autogenerate comparison must see no drift between models and migration.
    command.check(config)

    command.downgrade(config, "base")
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert not ({"tickets", "evaluations", "decisions", "reviews"} & tables)


async def test_readiness_rejects_an_unmigrated_database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    result = await check_database(engine)
    await engine.dispose()

    assert result.ready is False
    assert result.database == "ready"
    assert result.current_revision is None
    assert result.expected_revision == EXPECTED_DB_REVISION


def test_ready_endpoint_confirms_database_revision(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ready",
        "expected_revision": EXPECTED_DB_REVISION,
        "current_revision": EXPECTED_DB_REVISION,
    }


def test_health_reports_phase_five_version(client):
    assert client.get("/health").json()["version"] == "0.5.0"
