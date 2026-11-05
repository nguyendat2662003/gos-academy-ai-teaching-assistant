"""Structure-first chunking (DECISIONS D-09).

Each parsed Section becomes one chunk unless it exceeds `max_tokens`; long sections are packed sentence by
sentence up to `target_tokens` with ~`overlap_ratio` trailing overlap, never cutting inside a sentence.
FAQ rows are never split. Every chunk starts with a context line (document + section) so it stays
self-explanatory for both embedding and the LLM.
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.ingestion.injection import find_injection
from app.ingestion.text import estimate_tokens, split_sentences
from app.ingestion.types import ParsedDocument, Section


@dataclass
class ChunkDraft:
    content: str
    location: str
    section_code: str | None
    is_faq: bool
    token_count: int
    flagged_injection: bool
    injection_rule: str | None = None


def context_line(doc: ParsedDocument, section: Section) -> str:
    """e.g. '[Tài liệu: DOC-GS-01 – 01 | GIÁO TRÌNH MẪU … · Mục: GS-02 SUMIFS và COUNTIFS …]'"""
    source = " – ".join(p for p in (doc.doc_code, doc.title or doc.filename) if p)
    where = " ".join((section.title or section.location).split())
    return f"[Tài liệu: {source} · Mục: {where}]"


def _pack(sentences: list[str], target: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in sentences:
        cost = estimate_tokens(sentence)
        if current and size + cost > target:
            pieces.append(" ".join(current))
            # carry trailing sentences as overlap
            carried: list[str] = []
            carried_size = 0
            for prev in reversed(current):
                prev_cost = estimate_tokens(prev)
                if carried_size + prev_cost > overlap:
                    break
                carried.insert(0, prev)
                carried_size += prev_cost
            current, size = carried, carried_size
        current.append(sentence)
        size += cost
    if current:
        pieces.append(" ".join(current))
    return pieces


def split_section(text: str, max_tokens: int, target_tokens: int, overlap_ratio: float) -> list[str]:
    if estimate_tokens(text) <= max_tokens:
        return [text]
    return _pack(split_sentences(text), target_tokens, int(target_tokens * overlap_ratio))


def chunk_document(doc: ParsedDocument) -> list[ChunkDraft]:
    s = get_settings()
    drafts: list[ChunkDraft] = []
    for section in doc.sections:
        bodies = (
            [section.text]
            if section.is_faq
            else split_section(section.text, s.chunk_max_tokens, s.chunk_target_tokens, s.chunk_overlap_ratio)
        )
        header = context_line(doc, section)
        for i, body in enumerate(bodies, start=1):
            location = (
                section.location if len(bodies) == 1 else f"{section.location} (phần {i}/{len(bodies)})"
            )
            content = f"{header}\n{body}"
            rule = find_injection(body)
            drafts.append(
                ChunkDraft(
                    content=content,
                    location=location,
                    section_code=section.section_code,
                    is_faq=section.is_faq,
                    token_count=estimate_tokens(content),
                    flagged_injection=rule is not None,
                    injection_rule=rule,
                )
            )
    return drafts
