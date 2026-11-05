"""Initial schema: pgvector extension + all MVP tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-05

The embedding column size is taken from EMBEDDING_DIM at migration time. Changing the embedding
model/dimension later requires a new migration that alters the column, followed by a full reindex.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import get_settings

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=None if nullable else sa.func.now(),
        nullable=nullable,
    )


def upgrade() -> None:
    dim = get_settings().embedding_dim
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "classes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_shared", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("instructor_name", sa.String(255)),
        sa.Column("instructor_contact", sa.String(255)),
        _ts("created_at"),
        _ts("updated_at"),
    )

    op.create_table(
        "channel_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("external_group_id", sa.String(255), nullable=False),
        sa.Column("class_id", sa.String(64), sa.ForeignKey("classes.id"), nullable=False),
        sa.UniqueConstraint("channel", "external_group_id", name="uq_channel_groups_channel"),
    )
    op.create_index("ix_channel_groups_class_id", "channel_groups", ["class_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("class_id", sa.String(64), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("doc_code", sa.String(64)),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("warnings", postgresql.JSONB()),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("class_id", "filename", "version", name="uq_documents_class_id"),
    )
    op.create_index("ix_documents_class_status", "documents", ["class_id", "status"])

    op.create_table(
        "handoff_tickets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("class_id", sa.String(64), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("request_id", sa.String(32)),
        sa.Column("channel", sa.String(32)),
        sa.Column("external_group_id", sa.String(255)),
        sa.Column("reply_to", sa.String(255)),
        sa.Column("question_redacted", sa.Text(), nullable=False),
        sa.Column("user_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("check_detail", postgresql.JSONB()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assignee", sa.String(255)),
        sa.Column("instructor_answer", sa.Text()),
        sa.Column("promoted_to_faq", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("answered_at", nullable=True),
    )
    op.create_index("ix_tickets_class_status", "handoff_tickets", ["class_id", "status"])

    op.create_table(
        "faq_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("class_id", sa.String(64), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_ticket_id", sa.BigInteger(), sa.ForeignKey("handoff_tickets.id")),
        sa.Column("approved_by", sa.String(255)),
        _ts("approved_at", nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_faq_entries_class_id", "faq_entries", ["class_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("document_id", sa.BigInteger(), sa.ForeignKey("documents.id", ondelete="CASCADE")),
        sa.Column("faq_entry_id", sa.BigInteger(), sa.ForeignKey("faq_entries.id", ondelete="CASCADE")),
        sa.Column("class_id", sa.String(64), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("section_code", sa.String(64)),
        sa.Column("location", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(dim)),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, content)", persisted=True),
        ),
        sa.Column("flagged_injection", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint(
            "(document_id IS NULL) <> (faq_entry_id IS NULL)",
            name="ck_chunks_exactly_one_parent",
        ),
    )
    op.create_index("ix_chunks_class_id", "chunks", ["class_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_faq_entry_id", "chunks", ["faq_entry_id"])
    op.create_index(
        "ix_chunks_embedding_hnsw", "chunks", ["embedding"],
        postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")

    op.create_table(
        "processed_events",
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        _ts("received_at"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("channel", "event_id", name="pk_processed_events"),
    )

    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("class_id", sa.String(64), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("user_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_turns_scope", "conversation_turns", ["class_id", "user_hash", "created_at"])

    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("external_group_id", sa.String(255), nullable=False),
        sa.Column("event_id", sa.String(255)),
        sa.Column("reply_to", sa.String(255)),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _ts("created_at"),
    )
    op.create_index(
        "uq_outbox_channel_event", "outbox", ["channel", "event_id"],
        unique=True, postgresql_where=sa.text("event_id IS NOT NULL"),
    )
    op.create_index("ix_outbox_group", "outbox", ["channel", "external_group_id", "id"])

    op.create_table(
        "request_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("request_id", sa.String(32), nullable=False),
        sa.Column("class_id", sa.String(64)),
        sa.Column("channel", sa.String(32)),
        sa.Column("event_id", sa.String(255)),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("handoff_reason", sa.String(32)),
        sa.Column("retrieval_top_score", sa.Float()),
        sa.Column("cited_chunk_ids", postgresql.JSONB()),
        sa.Column("model", sa.String(128)),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("embedding_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 8)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("error_code", sa.String(64)),
        _ts("created_at"),
    )
    op.create_index("ix_request_logs_request_id", "request_logs", ["request_id"])
    op.create_index("ix_request_logs_class_created", "request_logs", ["class_id", "created_at"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("request_id", sa.String(32)),
        sa.Column("class_id", sa.String(64)),
        sa.Column("user_hash", sa.String(64)),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("detail_redacted", sa.Text()),
        _ts("created_at"),
    )
    op.create_index("ix_security_events_created", "security_events", ["created_at"])


def downgrade() -> None:
    for table in (
        "security_events", "request_logs", "outbox", "conversation_turns", "processed_events",
        "chunks", "faq_entries", "handoff_tickets", "documents", "channel_groups", "classes",
    ):
        op.drop_table(table)
