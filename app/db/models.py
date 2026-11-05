"""SQLAlchemy ORM models (single PostgreSQL DB: metadata, vectors, logs, tickets).

Status/outcome/reason columns are plain strings validated by the Python enums below
(easier to evolve than native PG enums; see DECISIONS.md).
"""

from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---------------------------------------------------------------- enums


class SourceType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    FAQ = "faq"


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    DELETED = "deleted"


class Outcome(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial"  # answered what the material covers + handoff for the rest (D-04)
    HANDOFF = "handoff"
    REFUSED = "refused"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class HandoffReason(StrEnum):
    NO_CONTEXT = "no_context"
    LOW_CONFIDENCE = "low_confidence"
    PARTIAL_COVERAGE = "partial_coverage"
    POLICY = "policy"
    SENSITIVE = "sensitive"
    ERROR = "error"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ANSWERED = "answered"
    CLOSED = "closed"


class SecurityEventType(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    SECRET_EXFILTRATION = "secret_exfiltration"  # noqa: S105 - event type label, not a secret
    CROSS_CLASS_REQUEST = "cross_class_request"
    SECRET_IN_MESSAGE = "secret_in_message"  # noqa: S105 - event type label, not a secret
    INVALID_SIGNATURE = "invalid_signature"
    RATE_LIMITED = "rate_limited"


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------- classes & channels


class ClassRoom(Base):
    """A class (or the shared COMMON scope when is_shared=True)."""

    __tablename__ = "classes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    instructor_name: Mapped[str | None] = mapped_column(String(255))
    instructor_contact: Mapped[str | None] = mapped_column(String(255))  # internal only
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChannelGroup(Base):
    """Maps an external chat group to exactly one class."""

    __tablename__ = "channel_groups"
    __table_args__ = (UniqueConstraint("channel", "external_group_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))
    external_group_id: Mapped[str] = mapped_column(String(255))
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id"), index=True)


# ---------------------------------------------------------------- knowledge base


class Document(Base):
    """One version of the part of one source file that belongs to one scope (a class or COMMON).

    A source file is identified by (origin_scope, filename): origin_scope is the class/folder it was uploaded
    under. A mixed file uploaded under COMMON yields one Document per scope it contains (D-02).
    """

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "origin_scope", "class_id", "filename", "version", name="uq_documents_origin_version"
        ),
        Index("ix_documents_class_status", "class_id", "status"),
        Index("ix_documents_source_file", "origin_scope", "filename", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id"))
    origin_scope: Mapped[str] = mapped_column(ForeignKey("classes.id"))
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str | None] = mapped_column(String(512))  # stored original, used by reindex
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    embedding_model: Mapped[str | None] = mapped_column(String(128))  # priced at query time (stats)
    doc_code: Mapped[str | None] = mapped_column(String(64))  # e.g. DOC-GS-01, used in citations
    source_type: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=DocumentStatus.PROCESSING)
    warnings: Mapped[list | None] = mapped_column(JSONB)  # e.g. pages without text
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FaqEntry(Base):
    """Instructor-approved Q&A pair, indexed as a chunk of its class."""

    __tablename__ = "faq_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # xlsx | instructor
    source_ticket_id: Mapped[int | None] = mapped_column(ForeignKey("handoff_tickets.id"))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _now()


class Chunk(Base):
    """A retrievable unit. class_id is denormalised so every search filters on it directly."""

    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("(document_id IS NULL) <> (faq_entry_id IS NULL)", name="exactly_one_parent"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    faq_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("faq_entries.id", ondelete="CASCADE"), index=True
    )
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16))
    section_code: Mapped[str | None] = mapped_column(String(64))  # e.g. GS-02
    location: Mapped[str] = mapped_column(String(255))  # e.g. "GS-02 SUMIFS…", "trang 14"
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, content)", persisted=True)
    )
    flagged_injection: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()


# ---------------------------------------------------------------- events & conversation


class ProcessedEvent(Base):
    """Idempotency ledger: the composite PK makes duplicate inserts fail atomically."""

    __tablename__ = "processed_events"
    __table_args__ = (PrimaryKeyConstraint("channel", "event_id"),)

    channel: Mapped[str] = mapped_column(String(32))
    event_id: Mapped[str] = mapped_column(String(255))
    received_at: Mapped[datetime] = _now()
    status: Mapped[str] = mapped_column(String(32), default="received")


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (Index("ix_turns_scope", "class_id", "user_hash", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id"))
    user_hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)  # redacted
    created_at: Mapped[datetime] = _now()


class Outbox(Base):
    """Messages the bot sent through the mock adapter (demo + test evidence)."""

    __tablename__ = "outbox"
    __table_args__ = (
        Index(
            "uq_outbox_channel_event",
            "channel",
            "event_id",
            unique=True,
            postgresql_where=text("event_id IS NOT NULL"),
        ),
        Index("ix_outbox_group", "channel", "external_group_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))
    external_group_id: Mapped[str] = mapped_column(String(255))
    event_id: Mapped[str | None] = mapped_column(String(255))  # null for instructor messages
    reply_to: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))  # answer | handoff | refusal | notice | instructor
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


# ---------------------------------------------------------------- operations


class RequestLog(Base):
    __tablename__ = "request_logs"
    __table_args__ = (
        Index("ix_request_logs_class_created", "class_id", "created_at"),
        Index("ix_request_logs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(32), index=True)
    class_id: Mapped[str | None] = mapped_column(String(64))
    channel: Mapped[str | None] = mapped_column(String(32))
    event_id: Mapped[str | None] = mapped_column(String(255))
    outcome: Mapped[str] = mapped_column(String(16))
    handoff_reason: Mapped[str | None] = mapped_column(String(32))
    retrieval_top_score: Mapped[float | None] = mapped_column(Float)
    cited_chunk_ids: Mapped[list | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    cost_usd: Mapped[float | None] = mapped_column(Numeric(14, 8))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


class HandoffTicket(Base):
    __tablename__ = "handoff_tickets"
    __table_args__ = (Index("ix_tickets_class_status", "class_id", "status"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id"))
    request_id: Mapped[str | None] = mapped_column(String(32))
    channel: Mapped[str | None] = mapped_column(String(32))
    external_group_id: Mapped[str | None] = mapped_column(String(255))  # to post the answer back
    reply_to: Mapped[str | None] = mapped_column(String(255))
    question_redacted: Mapped[str] = mapped_column(Text)
    user_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    check_detail: Mapped[dict | None] = mapped_column(JSONB)  # verification results
    status: Mapped[str] = mapped_column(String(16), default=TicketStatus.OPEN)
    assignee: Mapped[str | None] = mapped_column(String(255))
    instructor_answer: Mapped[str | None] = mapped_column(Text)
    promoted_to_faq: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_created", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(32))
    class_id: Mapped[str | None] = mapped_column(String(64))
    user_hash: Mapped[str | None] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))
    detail_redacted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
