"""documents: origin_scope, storage_path, embedding_tokens; uniqueness per source file.

Revision ID: 0002_document_origin
Revises: 0001_initial
Create Date: 2026-11-05
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_document_origin"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("origin_scope", sa.String(64), nullable=True))
    op.execute("UPDATE documents SET origin_scope = class_id")
    op.alter_column("documents", "origin_scope", nullable=False)
    op.create_foreign_key(
        "fk_documents_origin_scope_classes", "documents", "classes", ["origin_scope"], ["id"]
    )
    op.add_column("documents", sa.Column("storage_path", sa.String(512)))
    op.add_column(
        "documents",
        sa.Column("embedding_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.drop_constraint("uq_documents_class_id", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_documents_origin_version", "documents", ["origin_scope", "class_id", "filename", "version"]
    )
    op.create_index("ix_documents_source_file", "documents", ["origin_scope", "filename", "status"])


def downgrade() -> None:
    op.drop_index("ix_documents_source_file", "documents")
    op.drop_constraint("uq_documents_origin_version", "documents", type_="unique")
    op.create_unique_constraint("uq_documents_class_id", "documents", ["class_id", "filename", "version"])
    op.drop_column("documents", "embedding_tokens")
    op.drop_column("documents", "storage_path")
    op.drop_constraint("fk_documents_origin_scope_classes", "documents", type_="foreignkey")
    op.drop_column("documents", "origin_scope")
