"""Add provenance-aware deterministic graph facts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260804_0004"
down_revision: str | None = "20260804_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_facts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(160), nullable=False),
        sa.Column("predicate", sa.String(80), nullable=False),
        sa.Column("object_type", sa.String(40), nullable=False),
        sa.Column("object_id", sa.String(160), nullable=False),
        sa.Column("object_value", sa.String(160)),
        sa.Column(
            "source_document_id",
            sa.String(32),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("evidence", sa.String(500), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, column in (
        ("subject_id", "subject_id"),
        ("predicate", "predicate"),
        ("object_id", "object_id"),
        ("source_document_id", "source_document_id"),
        ("observed_at", "observed_at"),
    ):
        op.create_index(f"ix_graph_facts_{name}", "graph_facts", [column])


def downgrade() -> None:
    op.drop_table("graph_facts")
