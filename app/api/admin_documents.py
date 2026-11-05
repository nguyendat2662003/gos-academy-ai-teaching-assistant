"""Admin API for the knowledge base: list, upload, delete, re-index documents (X-Admin-Key)."""

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.classes import get_registry
from app.core.config import get_settings
from app.db.models import Chunk, Document, DocumentStatus
from app.db.session import get_session
from app.ingestion import indexer
from app.providers.base import EmbeddingProvider
from app.providers.registry import ProviderConfigError, get_embedding_provider

router = APIRouter(prefix="/admin/documents", tags=["admin"], dependencies=[Depends(require_admin)])


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
) -> list[DocumentOut]:
    chunk_count = select(Chunk.document_id, func.count().label("n")).group_by(Chunk.document_id).subquery()
    stmt = (
        select(Document, func.coalesce(chunk_count.c.n, 0))
        .outerjoin(chunk_count, chunk_count.c.document_id == Document.id)
        .order_by(Document.class_id, Document.filename, Document.version)
    )
    if class_id:
        stmt = stmt.where(Document.class_id == class_id)
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
) -> dict:
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
async def delete_document(document_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    if not await indexer.delete_document(session, document_id):
        raise HTTPException(404, "document not found or already deleted")
    return {"id": document_id, "status": DocumentStatus.DELETED}


@router.post("/{document_id}/reindex")
async def reindex_document(
    document_id: int,
    session: AsyncSession = Depends(get_session),
    embedder: EmbeddingProvider = Depends(embedding_provider),
) -> dict:
    try:
        report = await indexer.reindex_document(
            session, document_id, embedder=embedder, registry=get_registry()
        )
    except LookupError as exc:
        raise HTTPException(404, "document not found") from exc
    except indexer.IngestError as exc:
        raise HTTPException(409, str(exc)) from exc
    return asdict(report)
