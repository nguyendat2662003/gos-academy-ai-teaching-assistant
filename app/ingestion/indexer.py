"""Index a source file into the knowledge base: parse -> chunk -> scope -> embed -> versioned swap.

Rules (CLAUDE.md §7, DECISIONS D-02, D-36..D-39):
- Each chunk is assigned a scope from its section-code prefix (config/classes.yaml). A file uploaded under a
  class may only contain that class's sections; only a file uploaded under the shared scope (COMMON) may be
  split across scopes. Anything else is refused before writing.
- Per scope, a content hash decides: unchanged -> skip; changed -> new version `processing`, embed,
  then in ONE transaction insert chunks, activate the new version, supersede the old one and
  delete its chunks.
- Retrieval only reads chunks of `active` documents, so a half-finished version is never visible.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.classes import ClassRegistry
from app.core.config import get_settings
from app.db import repositories as repo
from app.db.models import Chunk, Document, DocumentStatus, SecurityEventType, SourceType
from app.ingestion.chunker import ChunkDraft, chunk_document
from app.ingestion.parsers import SUPPORTED_SUFFIXES, parse_file
from app.ingestion.text import scope_prefix
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class IngestError(ValueError):
    """The file cannot be indexed as requested; nothing was written."""


class ScopeConflictError(IngestError):
    """A file uploaded under one class contains sections of another scope."""


@dataclass
class ScopeResult:
    scope: str
    status: str  # indexed | unchanged | removed | failed
    document_id: int | None = None
    version: int | None = None
    chunks: int = 0
    flagged: int = 0
    embedding_tokens: int = 0
    error: str | None = None


@dataclass
class IngestReport:
    filename: str
    origin_scope: str
    source_type: str
    warnings: list[str] = field(default_factory=list)
    results: list[ScopeResult] = field(default_factory=list)


# ------------------------------------------------------------------ pure helpers


def split_by_scope(
    drafts: list[ChunkDraft], origin_scope: str, registry: ClassRegistry
) -> dict[str, list[ChunkDraft]]:
    """Group chunks by target scope; refuse cross-scope content in a class-scoped upload."""
    shared = registry.shared_scope.id
    groups: dict[str, list[ChunkDraft]] = {}
    for draft in drafts:
        target = registry.scope_for_prefix(scope_prefix(draft.section_code)) or origin_scope
        if origin_scope != shared and target != origin_scope:
            raise ScopeConflictError(
                f"mục {draft.section_code} ({draft.location}) thuộc phạm vi {target}, "
                f"nhưng tài liệu được tải lên cho {origin_scope}"
            )
        groups.setdefault(target, []).append(draft)
    return groups


def scope_hash(drafts: list[ChunkDraft], embedding_key: str) -> str:
    """Hash of what would be indexed for one scope (content + location + embedding model).

    Per scope, so unrelated edits elsewhere in a mixed file do not re-embed this scope. The embedding key
    (provider:model:dim) is included so switching the embedding model re-embeds instead of silently keeping
    vectors from another model (D-38)."""
    h = hashlib.sha256(embedding_key.encode() + b"")
    for d in drafts:
        h.update(d.location.encode())
        h.update(b"\x1f")
        h.update(d.content.encode())
        h.update(b"\x1e")
    return h.hexdigest()


def store_original(data: bytes, filename: str) -> str:
    """Keep the uploaded bytes (content-addressed) so the document can be re-indexed later."""
    suffix = Path(filename).suffix.lower()
    root = Path(get_settings().storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{hashlib.sha256(data).hexdigest()}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return path.as_posix()


def safe_filename(name: str) -> str:
    """Strip any directory part a client may send; keep the original display name otherwise."""
    cleaned = Path(name.replace("\\", "/")).name.strip()
    if not cleaned or cleaned in {".", ".."}:
        raise IngestError("tên file không hợp lệ")
    return cleaned[:255]


# ------------------------------------------------------------------ main entry points


async def index_file(
    session: AsyncSession,
    *,
    data: bytes,
    filename: str,
    origin_scope: str,
    embedder: EmbeddingProvider,
    registry: ClassRegistry,
    force: bool = False,
) -> IngestReport:
    """Index (or re-index) one source file under `origin_scope`. `force` re-embeds even unchanged scopes."""
    filename = safe_filename(filename)
    if origin_scope not in registry.scope_ids:
        raise IngestError(f"phạm vi không tồn tại: {origin_scope}")
    source_type = SUPPORTED_SUFFIXES.get(Path(filename).suffix.lower())
    if source_type is None:
        raise IngestError(f"định dạng không hỗ trợ: {Path(filename).suffix or '(không có)'}")

    # File I/O and parsing are blocking: keep them off the event loop.
    storage_path = await asyncio.to_thread(store_original, data, filename)
    parsed = await asyncio.to_thread(parse_file, Path(storage_path))
    parsed.filename = filename
    drafts = chunk_document(parsed)
    if not drafts:
        raise IngestError("không trích xuất được nội dung nào: " + "; ".join(parsed.warnings))
    groups = split_by_scope(drafts, origin_scope, registry)  # raises before any DB write

    report = IngestReport(filename, origin_scope, source_type, warnings=list(parsed.warnings))
    active = await _active_documents(session, origin_scope, filename)
    embedding_key = f"{embedder.name}:{embedder.model}:{embedder.dim}"

    for scope, scope_drafts in groups.items():
        content_hash = scope_hash(scope_drafts, embedding_key)
        previous = active.get(scope)
        if previous is not None and previous.content_hash == content_hash and not force:
            report.results.append(
                ScopeResult(scope, "unchanged", previous.id, previous.version, len(scope_drafts))
            )
            continue
        report.results.append(
            await _index_scope(
                session,
                scope=scope,
                origin_scope=origin_scope,
                filename=filename,
                source_type=source_type,
                doc_code=parsed.doc_code,
                warnings=parsed.warnings,
                storage_path=storage_path,
                content_hash=content_hash,
                drafts=scope_drafts,
                previous=previous,
                embedder=embedder,
            )
        )

    # Scopes that disappeared from a mixed file: their old content must stop being retrievable.
    for scope, previous in active.items():
        if scope not in groups:
            await _retire(session, previous, DocumentStatus.DELETED)
            await session.commit()
            report.results.append(ScopeResult(scope, "removed", previous.id, previous.version))
    return report


async def delete_document(session: AsyncSession, document_id: int) -> bool:
    """Soft-delete a document and drop its chunks. False if not found or already deleted."""
    doc = await session.get(Document, document_id)
    if doc is None or doc.status == DocumentStatus.DELETED:
        return False
    await _retire(session, doc, DocumentStatus.DELETED)
    await session.commit()
    logger.info("document deleted", extra={"fields": {"document_id": document_id, "class_id": doc.class_id}})
    return True


async def reindex_document(
    session: AsyncSession, document_id: int, *, embedder: EmbeddingProvider, registry: ClassRegistry
) -> IngestReport:
    """Re-parse the stored original of a document's source file and re-embed it (new version)."""
    doc = await session.get(Document, document_id)
    if doc is None:
        raise LookupError(document_id)
    if doc.status == DocumentStatus.DELETED:
        raise IngestError("tài liệu đã bị xóa; hãy tải lên lại")
    missing = IngestError("không còn bản gốc của tài liệu để đánh lại chỉ mục; hãy tải lên lại")
    if not doc.storage_path:
        raise missing
    try:
        data = await asyncio.to_thread(Path(doc.storage_path).read_bytes)
    except OSError as exc:
        raise missing from exc
    return await index_file(
        session,
        data=data,
        filename=doc.filename,
        origin_scope=doc.origin_scope,
        embedder=embedder,
        registry=registry,
        force=True,
    )


# ------------------------------------------------------------------ internals


async def _active_documents(session: AsyncSession, origin_scope: str, filename: str) -> dict[str, Document]:
    rows = await session.execute(
        select(Document).where(
            Document.origin_scope == origin_scope,
            Document.filename == filename,
            Document.status == DocumentStatus.ACTIVE,
        )
    )
    return {d.class_id: d for d in rows.scalars()}


async def _next_version(session: AsyncSession, origin_scope: str, scope: str, filename: str) -> int:
    current = await session.scalar(
        select(func.max(Document.version)).where(
            Document.origin_scope == origin_scope, Document.class_id == scope, Document.filename == filename
        )
    )
    return (current or 0) + 1


async def _embed(embedder: EmbeddingProvider, drafts: list[ChunkDraft]) -> tuple[list[list[float]], int]:
    batch = get_settings().embedding_batch_size
    vectors: list[list[float]] = []
    tokens = 0
    for start in range(0, len(drafts), batch):
        result = await embedder.embed([d.content for d in drafts[start : start + batch]], "document")
        vectors.extend(result.vectors)
        tokens += result.tokens
    return vectors, tokens


async def _retire(session: AsyncSession, doc: Document, status: DocumentStatus) -> None:
    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    doc.status = status


async def _index_scope(
    session: AsyncSession,
    *,
    scope: str,
    origin_scope: str,
    filename: str,
    source_type: str,
    doc_code: str | None,
    warnings: list[str],
    storage_path: str,
    content_hash: str,
    drafts: list[ChunkDraft],
    previous: Document | None,
    embedder: EmbeddingProvider,
) -> ScopeResult:
    new = Document(
        class_id=scope,
        origin_scope=origin_scope,
        filename=filename,
        doc_code=doc_code,
        source_type=source_type,
        version=await _next_version(session, origin_scope, scope, filename),
        content_hash=content_hash,
        status=DocumentStatus.PROCESSING,
        warnings=warnings or None,
        storage_path=storage_path,
    )
    session.add(new)
    await session.commit()  # the `processing` version is visible to admins, never to retrieval

    try:
        vectors, tokens = await _embed(embedder, drafts)
    except Exception as exc:
        new.status = DocumentStatus.FAILED
        await session.commit()
        logger.error(
            "embedding failed",
            exc_info=True,
            extra={"fields": {"document_id": new.id, "class_id": scope}},
        )
        return ScopeResult(scope, "failed", new.id, new.version, error=type(exc).__name__)

    # Single transaction: new chunks + activate new + supersede old (and drop its chunks).
    for draft, vector in zip(drafts, vectors, strict=True):
        session.add(
            Chunk(
                document_id=new.id,
                class_id=scope,
                source_type=SourceType.FAQ if draft.is_faq else source_type,
                section_code=draft.section_code,
                location=draft.location,
                content=draft.content,
                token_count=draft.token_count,
                embedding=vector,
                flagged_injection=draft.flagged_injection,
            )
        )
        if draft.flagged_injection:
            _report_flag(session, scope, filename, draft)
    if previous is not None:
        await _retire(session, previous, DocumentStatus.SUPERSEDED)
    new.status = DocumentStatus.ACTIVE
    new.embedding_tokens = tokens
    new.embedding_model = embedder.model
    await session.commit()

    flagged = sum(d.flagged_injection for d in drafts)
    logger.info(
        "document indexed",
        extra={
            "fields": {
                "document_id": new.id,
                "class_id": scope,
                "version": new.version,
                "chunks": len(drafts),
                "flagged": flagged,
                "embedding_tokens": tokens,
            }
        },
    )
    return ScopeResult(scope, "indexed", new.id, new.version, len(drafts), flagged, tokens)


def _report_flag(session: AsyncSession, scope: str, filename: str, draft: ChunkDraft) -> None:
    logger.warning(
        "instruction-like text in document",
        extra={"fields": {"class_id": scope, "filename": filename, "location": draft.location}},
    )
    repo.add_security_event(
        session,
        SecurityEventType.PROMPT_INJECTION,
        request_id=None,
        class_id=scope,
        detail=f"source=document;file={filename};location={draft.location}",
    )
