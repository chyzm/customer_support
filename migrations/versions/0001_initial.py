"""Create the initial support triage schema.

Revision ID: 0001_initial
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("triage_state", sa.String(length=20), nullable=False),
        sa.Column("triage_error", sa.String(length=300), nullable=True),
        sa.Column("queue", sa.String(length=50), nullable=True),
        sa.Column("priority", sa.String(length=2), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=False),
        sa.Column("handling", sa.String(length=20), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tickets_needs_review", "tickets", ["needs_review"])
    op.create_index("ix_tickets_priority", "tickets", ["priority"])
    op.create_index("ix_tickets_queue", "tickets", ["queue"])
    op.create_index("ix_tickets_status", "tickets", ["status"])
    op.create_index("ix_tickets_triage_state", "tickets", ["triage_state"])

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluations_ticket_id", "evaluations", ["ticket_id"])

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("evaluation_id", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("queue", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.String(length=2), nullable=False),
        sa.Column("escalate", sa.Boolean(), nullable=False),
        sa.Column("handling", sa.String(length=20), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluations.id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_ticket_id", "decisions", ["ticket_id"])

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("queue", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.String(length=2), nullable=False),
        sa.Column("escalate", sa.Boolean(), nullable=False),
        sa.Column("agreed", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_ticket_id", "reviews", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_reviews_ticket_id", table_name="reviews")
    op.drop_table("reviews")
    op.drop_index("ix_decisions_ticket_id", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_evaluations_ticket_id", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_tickets_triage_state", table_name="tickets")
    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_index("ix_tickets_queue", table_name="tickets")
    op.drop_index("ix_tickets_priority", table_name="tickets")
    op.drop_index("ix_tickets_needs_review", table_name="tickets")
    op.drop_table("tickets")
