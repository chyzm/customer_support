"""Database-level behaviour that the API tests cannot see."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import ReviewRecord, Ticket
from app.db.session import create_engine, create_session_factory, init_db, to_async_url


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("sqlite:///./triage.db", "sqlite+aiosqlite:///./triage.db"),
        ("sqlite:///:memory:", "sqlite+aiosqlite:///:memory:"),
        ("sqlite+aiosqlite:///x.db", "sqlite+aiosqlite:///x.db"),
    ],
)
def test_url_is_converted_to_async_driver(given, expected):
    assert to_async_url(given) == expected


async def test_data_survives_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'persist.db'}"

    engine = create_engine(url)
    await init_db(engine)
    async with create_session_factory(engine)() as session:
        session.add(Ticket(subject="Stored subject", message="Stored message body"))
        await session.commit()
    await engine.dispose()  # "shut the app down"

    engine = create_engine(url)  # "start it again"
    async with create_session_factory(engine)() as session:
        ticket = await session.get(Ticket, 1)
        assert ticket is not None
        assert ticket.subject == "Stored subject"
        assert ticket.created_at.tzinfo is not None  # UTC restored on read
    await engine.dispose()


async def test_foreign_keys_are_enforced():
    """SQLite ignores foreign keys unless PRAGMA foreign_keys=ON is set on every connection."""
    engine = create_engine("sqlite:///:memory:")
    await init_db(engine)
    async with create_session_factory(engine)() as session:
        session.add(ReviewRecord(
            ticket_id=999, decision_id=999, reviewer="x", action="confirm",
            queue="billing", priority="P3", escalate=False, agreed=True,
        ))
        with pytest.raises(IntegrityError):
            await session.commit()
    await engine.dispose()
