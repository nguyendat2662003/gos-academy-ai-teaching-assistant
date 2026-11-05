"""Hybrid retrieval: pgvector cosine top-k + PostgreSQL full-text top-k, fused with Reciprocal Rank Fusion.

THE ONLY module that searches chunks for answering. Every query is scoped in SQL to
`class_id IN (:class_id, <shared scope>)` and to retrievable sources (active documents, active FAQ entries)
— CLAUDE.md §1.2, §7. `class_id` is a required keyword-only argument with no default.
"""

import math
import re
from dataclasses import dataclass

from sqlalchemy import Select, and_, case, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.classes import ClassRegistry
from app.db.models import Chunk, Document, DocumentStatus, FaqEntry
from app.providers.base import EmbeddingProvider

RRF_K = 60  # standard constant from the RRF paper; dampens the weight of top ranks
CANDIDATES_PER_LIST = 20

# Very frequent Vietnamese/English function words: they match almost every chunk in OR-mode full-text search.
_STOPWORDS = {
    "là", "gì", "có", "không", "và", "của", "cho", "em", "mình", "thì", "thế", "nào", "được", "bị", "ở",
    "khi", "này", "đó", "với", "các", "những", "một", "trong", "để", "làm", "sao", "ạ", "ơi", "nhé",
    "hả", "vậy",
    "the", "a", "an", "is", "are", "of", "to", "in", "how", "what", "do", "does",
}  # fmt: skip
_TERM_RE = re.compile(r"\w+", re.UNICODE)


@dataclass
class RetrievedChunk:
    chunk_id: int
    class_id: str
    source_type: str
    section_code: str | None
    location: str
    content: str
    doc_code: str | None
    filename: str | None  # None for instructor FAQ entries
    flagged_injection: bool
    vector_score: float | None = None  # cosine similarity (1 - cosine distance)
    text_rank: float | None = None
    rrf_score: float = 0.0

    @property
    def ref(self) -> str:
        """Id used in the prompt and in citations (e.g. 'c_123')."""
        return f"c_{self.chunk_id}"


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    top_vector_score: float | None  # threshold input: best cosine similarity of the vector list
    embedding_tokens: int


def allowed_scopes(class_id: str, registry: ClassRegistry) -> list[str]:
    """The scopes a class may read: itself + the shared scope.

    Rejects unknown ids and the shared id itself (COMMON is not a class)."""
    if class_id not in {c.id for c in registry.classes}:
        raise ValueError(f"unknown class id: {class_id!r}")
    return [class_id, registry.shared_scope.id]


def _base_query(scopes: list[str], *columns) -> Select:  # type: ignore[no-untyped-def]
    """Chunks of the given scopes whose source is currently retrievable."""
    return (
        select(
            Chunk.id,
            Chunk.class_id,
            Chunk.source_type,
            Chunk.section_code,
            Chunk.location,
            Chunk.content,
            Chunk.flagged_injection,
            Document.doc_code,
            Document.filename,
            *columns,
        )
        .outerjoin(Document, Document.id == Chunk.document_id)
        .outerjoin(FaqEntry, FaqEntry.id == Chunk.faq_entry_id)
        .where(
            Chunk.class_id.in_(scopes),
            or_(
                and_(Chunk.document_id.is_not(None), Document.status == DocumentStatus.ACTIVE),
                and_(Chunk.faq_entry_id.is_not(None), FaqEntry.active.is_(True)),
            ),
        )
    )


def query_terms(question: str) -> list[str]:
    """Distinct lower-cased word terms minus stopwords. Only \w characters: safe inside to_tsquery."""
    terms = [t for t in _TERM_RE.findall(question.lower()) if t not in _STOPWORDS and len(t) > 1]
    return list(dict.fromkeys(terms))[:20]


def fulltext_query(question: str) -> str | None:
    """OR-query of the meaningful terms ('lỗi | 401 | n8n'); None if nothing is left."""
    terms = query_terms(question)
    return " | ".join(terms) if terms else None


def _matches(term: str):  # type: ignore[no-untyped-def]
    return Chunk.tsv.op("@@")(func.to_tsquery("simple", term))


async def _idf_weights(session: AsyncSession, scopes: list[str], terms: list[str]) -> dict[str, float]:
    """idf(t) = ln(1 + N / df(t)) over the scope's retrievable chunks; absent terms are dropped.

    Vietnamese is tokenised per syllable, so common syllables ("xử", "lý", "lỗi") would otherwise outweigh
    rare, decisive terms ("401", "unauthorized"). One aggregate query, still scope-filtered (D-49)."""
    if not terms:
        return {}
    counts = [func.count().filter(_matches(t)).label(f"t{i}") for i, t in enumerate(terms)]
    row = (
        await session.execute(_base_query(scopes).with_only_columns(func.count().label("n"), *counts))
    ).one()
    total = row[0]
    return {t: math.log(1 + total / row[i + 1]) for i, t in enumerate(terms) if row[i + 1]}


def _row_to_chunk(row) -> RetrievedChunk:  # type: ignore[no-untyped-def]
    return RetrievedChunk(
        chunk_id=row.id,
        class_id=row.class_id,
        source_type=row.source_type,
        section_code=row.section_code,
        location=row.location,
        content=row.content,
        doc_code=row.doc_code,
        filename=row.filename,
        flagged_injection=row.flagged_injection,
    )


async def hybrid_search(
    session: AsyncSession,
    *,
    class_id: str,
    question: str,
    embedder: EmbeddingProvider,
    registry: ClassRegistry,
    top_k: int,
) -> RetrievalResult:
    """Top-k chunks for `question`, restricted to `class_id` + the shared scope."""
    scopes = allowed_scopes(class_id, registry)
    embedding = await embedder.embed([question], "query")
    query_vector = embedding.vectors[0]

    # pgvector >= 0.8: keep scanning the HNSW index until enough rows pass the WHERE filter.
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    distance = Chunk.embedding.cosine_distance(query_vector)
    vector_rows = (
        await session.execute(
            _base_query(scopes, (literal(1.0) - distance).label("similarity"))
            .where(Chunk.embedding.is_not(None))
            .order_by(distance)
            .limit(CANDIDATES_PER_LIST)
        )
    ).all()

    text_rows = []
    weights = await _idf_weights(session, scopes, query_terms(question))
    if weights:
        tsquery = func.to_tsquery("simple", " | ".join(weights))
        # Score = sum of idf over the distinct query terms the chunk contains.
        rank = sum((case((_matches(t), w), else_=0.0) for t, w in weights.items()), literal(0.0))
        text_rows = (
            await session.execute(
                _base_query(scopes, rank.label("rank"))
                .where(Chunk.tsv.op("@@")(tsquery))
                .order_by(rank.desc(), Chunk.id)
                .limit(CANDIDATES_PER_LIST)
            )
        ).all()

    fused: dict[int, RetrievedChunk] = {}
    for position, row in enumerate(vector_rows, start=1):
        chunk = fused.setdefault(row.id, _row_to_chunk(row))
        chunk.vector_score = float(row.similarity)
        chunk.rrf_score += 1.0 / (RRF_K + position)
    for position, row in enumerate(text_rows, start=1):
        chunk = fused.setdefault(row.id, _row_to_chunk(row))
        chunk.text_rank = float(row.rank)
        chunk.rrf_score += 1.0 / (RRF_K + position)
    await session.commit()  # end the transaction holding SET LOCAL

    ranked = sorted(fused.values(), key=lambda c: (-c.rrf_score, c.chunk_id))[:top_k]
    top_vector = float(vector_rows[0].similarity) if vector_rows else None
    return RetrievalResult(chunks=ranked, top_vector_score=top_vector, embedding_tokens=embedding.tokens)
