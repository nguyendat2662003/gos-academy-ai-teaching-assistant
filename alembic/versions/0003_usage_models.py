"""Usage accounting: embedding model per log/document/FAQ entry, FAQ embedding tokens, time index for stats.

Revision ID: 0003_usage_models
Revises: 0002_document_origin
Create Date: 2026-11-05
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_usage_models"
down_revision: str | None = "0002_document_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("request_logs", sa.Column("embedding_model", sa.String(128)))
    op.add_column("documents", sa.Column("embedding_model", sa.String(128)))
    op.add_column("faq_entries", sa.Column("embedding_model", sa.String(128)))
    op.add_column(
        "faq_entries",
        sa.Column("embedding_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index("ix_request_logs_created", "request_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_request_logs_created", "request_logs")
    op.drop_column("faq_entries", "embedding_tokens")
    op.drop_column("faq_entries", "embedding_model")
    op.drop_column("documents", "embedding_model")
    op.drop_column("request_logs", "embedding_model")
