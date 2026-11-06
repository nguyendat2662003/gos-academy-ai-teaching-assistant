"""Admin API for the knowledge base: list, upload, delete, re-index documents (X-Admin-Key).

Roles (D-83): admin = everything. Instructor = read own class + the shared COMMON material; upload, delete and
re-index only documents that belong to their class alone. A file uploaded under COMMON feeds several classes
(e.g. the mixed FAQ file), so changing it is an admin action.
"""

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_staff
from app.core.classes import get_registry
from app.core.config import get_settings
from app.db.models import Chunk, Document, DocumentStatus
from app.db.session import get_session
from app.ingestion import indexer
from app.providers.base import EmbeddingProvider
from app.providers.registry import ProviderConfigError, get_embedding_provider

router = APIRouter(prefix="/admin/documents", tags=["admin"], dependencies=[Depends(require_staff)])


class DocumentOut(BaseModel):
    id: int
    class_id: str
    origin_scope: str
    filename: str
    doc_code: str | None
    source_type: str
    version: int
    status: str
    chunks: int
    embedding_tokens: int
    warnings: list[str] | None
    created_at: datetime


def _check_upload_scope(principal: Principal, scope: str) -> None:
    if not principal.owns(scope):  # an instructor may only feed their own class (never COMMON)
        raise HTTPException(403, "instructor key: upload to own class only")


async def _editable_document(session: AsyncSession, document_id: int, principal: Principal) -> Document:
    """The document, if this caller may change it: 404 for another class, 403 for shared material."""
    doc = await session.get(Document, document_id)
    if doc is None or not principal.owns(doc.class_id):
        raise HTTPException(404, "document not found")
    if not principal.owns(doc.origin_scope):
        raise HTTPException(403, "shared document (uploaded under COMMON): admin key required")
    return doc


def embedding_provider() -> EmbeddingProvider:
    try:
        return get_embedding_provider()
    except ProviderConfigError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("")
async def list_documents(
    class_id: str | None = None,
    status: str | None = Query(default=DocumentStatus.ACTIVE, description="empty = all statuses"),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_staff),
) -> list[DocumentOut]:
    chunk_count = select(Chunk.document_id, func.count().label("n")).group_by(Chunk.document_id).subquery()
    stmt = (
        select(Document, func.coalesce(chunk_count.c.n, 0))
        .outerjoin(chunk_count, chunk_count.c.document_id == Document.id)
        .order_by(Document.class_id, Document.filename, Document.version)
    )
    if principal.is_admin:
        if class_id:
            stmt = stmt.where(Document.class_id == class_id)
    else:  # own class + the shared scope its students also read
        shared = get_registry().shared_scope.id
        if class_id and class_id not in (principal.class_id, shared):
            raise HTTPException(403, "instructor key: own class only")
        stmt = stmt.where(Document.class_id.in_([class_id] if class_id else [principal.class_id, shared]))
    if status:
        stmt = stmt.where(Document.status == status)
    rows = (await session.execute(stmt)).all()
    return [
        DocumentOut(
            id=d.id,
            class_id=d.class_id,
            origin_scope=d.origin_scope,
            filename=d.filename,
            doc_code=d.doc_code,
            source_type=d.source_type,
            version=d.version,
            status=d.status,
            chunks=n,
            embedding_tokens=d.embedding_tokens,
            warnings=d.warnings,
            created_at=d.created_at,
        )
        for d, n in rows
    ]


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    class_id: str = Form(..., description="class id, or COMMON for a file mixing several scopes"),
    session: AsyncSession = Depends(get_session),
    embedder: EmbeddingProvider = Depends(embedding_provider),
    principal: Principal = Depends(require_staff),
) -> dict:
    _check_upload_scope(principal, class_id)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"file lớn hơn {get_settings().max_upload_mb} MB")
    try:
        report = await indexer.index_file(
            session,
            data=data,
            filename=file.filename or "",
            origin_scope=class_id,
            embedder=embedder,
            registry=get_registry(),
        )
    except indexer.IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    return asdict(report)


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_staff),
) -> dict:
    await _editable_document(session, document_id, principal)
    if not await indexer.delete_document(session, document_id):
        raise HTTPException(404, "document not found or already deleted")
    return {"id": document_id, "status": DocumentStatus.DELETED}


@router.post("/{document_id}/reindex")
async def reindex_document(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    embedder: EmbeddingProvider = Depends(embedding_provider),
    principal: Principal = Depends(require_staff),
) -> dict:
    await _editable_document(session, document_id, principal)
    try:
        report = await indexer.reindex_document(
            session, document_id, embedder=embedder, registry=get_registry()
        )
    except LookupError as exc:
        raise HTTPException(404, "document not found") from exc
    except indexer.IngestError as exc:
        raise HTTPException(409, str(exc)) from exc
    return asdict(report)
