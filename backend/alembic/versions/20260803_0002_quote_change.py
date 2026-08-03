"""Persist the latest market quote change percentage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0002"
down_revision: str | None = "20260801_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stocks",
        sa.Column("change_pct", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("stocks", "change_pct")
