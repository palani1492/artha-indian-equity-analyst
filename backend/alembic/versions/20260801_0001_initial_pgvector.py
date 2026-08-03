"""Initial users, stocks, RAG documents, persona memory, and sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "20260801_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "users",
        sa.Column("id", sa.String(320), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(160)),
        sa.Column("picture", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "stocks",
        sa.Column("ticker", sa.String(20), primary_key=True),
        sa.Column("exchange", sa.String(3), nullable=False),
        sa.Column("bse_id", sa.String(20)),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("sector", sa.String(80), nullable=False),
        sa.Column("price_inr", sa.Numeric(20, 4), nullable=False),
        sa.Column("market_cap_crore", sa.Numeric(24, 4)),
        sa.Column("pe_ratio", sa.Numeric(16, 4)),
        sa.Column("debt_to_equity", sa.Numeric(16, 4)),
        sa.Column("dividend_yield", sa.Numeric(16, 4)),
        sa.Column("roe", sa.Numeric(16, 4)),
        sa.Column("revenue_growth", sa.Numeric(16, 4)),
        sa.Column("sentiment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("change_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "ticker",
            sa.String(20),
            sa.ForeignKey("stocks.ticker", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("sentiment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impact", sa.String(40), nullable=False),
        sa.Column("event_tag", sa.String(80), nullable=False),
        sa.Column("mentioned_tickers", sa.JSON(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.UniqueConstraint("ticker", "content_hash", name="uq_documents_ticker_hash"),
    )
    op.create_index("ix_documents_ticker", "documents", ["ticker"])
    op.create_index("ix_documents_published_at", "documents", ["published_at"])
    op.create_index(
        "ix_documents_embedding_hnsw",
        "documents",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "personas",
        sa.Column("user_id", sa.String(320), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "stock_follows",
        sa.Column("user_id", sa.String(320), primary_key=True),
        sa.Column(
            "ticker",
            sa.String(20),
            sa.ForeignKey("stocks.ticker", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(320),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("stock_follows")
    op.drop_table("personas")
    op.drop_table("documents")
    op.drop_table("stocks")
    op.drop_table("users")
