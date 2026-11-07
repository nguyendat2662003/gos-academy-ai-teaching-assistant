"""FAQ review: flag approved FAQ entries when their class's material changes (D-89).

Revision ID: 0004_faq_review
Revises: 0003_usage_models
Create Date: 2026-11-07
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_faq_review"
down_revision: str | None = "0003_usage_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "faq_entries",
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("faq_entries", sa.Column("review_reason", sa.String(255)))
    op.add_column("faq_entries", sa.Column("updated_at", sa.DateTime(timezone=True)))
    # Documents are matched by file name OR document code when a new version arrives (D-88).
    op.create_index("ix_documents_doc_code", "documents", ["origin_scope", "doc_code", "status"])


def downgrade() -> None:
    op.drop_index("ix_documents_doc_code", "documents")
    op.drop_column("faq_entries", "updated_at")
    op.drop_column("faq_entries", "review_reason")
    op.drop_column("faq_entries", "needs_review")
