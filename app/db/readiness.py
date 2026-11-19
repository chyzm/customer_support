from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.version import EXPECTED_DB_REVISION


@dataclass(frozen=True)
class DatabaseReadiness:
    ready: bool
    database: str
    expected_revision: str
    current_revision: str | None


async def check_database(engine: AsyncEngine) -> DatabaseReadiness:
    """Check connectivity and migration state without modifying the database."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            try:
                current = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            except SQLAlchemyError:
                current = None
    except SQLAlchemyError:
        return DatabaseReadiness(False, "unavailable", EXPECTED_DB_REVISION, None)

    return DatabaseReadiness(
        ready=current == EXPECTED_DB_REVISION,
        database="ready",
        expected_revision=EXPECTED_DB_REVISION,
        current_revision=current,
    )
