"""Database schema version expected by this application release.

Update this constant whenever a new Alembic migration becomes the head. The
readiness endpoint compares it with the database's `alembic_version` row.
"""

EXPECTED_DB_REVISION = "0001_initial"
