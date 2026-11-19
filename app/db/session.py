from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base


def to_async_url(url: str) -> str:
    """Accept the familiar `sqlite:///file.db` form and select the async driver."""
    if url.startswith("sqlite:") and not url.startswith("sqlite+"):
        return url.replace("sqlite:", "sqlite+aiosqlite:", 1)
    return url


def create_engine(database_url: str) -> AsyncEngine:
    url = to_async_url(database_url)
    in_memory = ":memory:" in url or url.rstrip("/").endswith("sqlite+aiosqlite:")

    # An in-memory SQLite database exists only inside ONE connection. StaticPool
    # makes every session share that single connection; otherwise each new
    # connection would see an empty database.
    engine = create_async_engine(url, poolclass=StaticPool) if in_memory else create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        # SQLite does NOT enforce foreign keys unless asked, per connection.
        cursor.execute("PRAGMA foreign_keys=ON")
        # Wait up to 5s for a lock instead of failing instantly with "database is locked".
        cursor.execute("PRAGMA busy_timeout=5000")
        if not in_memory:
            # WAL lets readers continue while one writer writes.
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    # expire_on_commit=False: after commit, objects keep their loaded values.
    # With async sessions, an expired attribute would trigger a lazy load,
    # which raises an error outside an awaited call.
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """Create tables for isolated low-level tests only.

    Application startup and deployed environments use Alembic migrations. This
    helper remains for database unit tests that intentionally exercise metadata.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
