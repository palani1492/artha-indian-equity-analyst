"""Add source quality tiers to indexed documents."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260804_0005"
down_revision: str | None = "20260804_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "source_tier",
            sa.String(20),
            nullable=False,
            server_default="secondary",
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "source_tier")
