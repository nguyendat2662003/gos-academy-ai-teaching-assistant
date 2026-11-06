"""Citation line built from chunk metadata — never from LLM text (DECISIONS D-03).

📚 Nguồn: DOC-AUTO-01 – AUTO-03 (02_Giao_trinh_AI_Automation_n8n.docx);
          DOC-FAQ-01 – AUTO-CLASS-02, dòng 2 (03_….docx)
"""

from app.agent.messages import SOURCES_PREFIX
from app.retrieval.search import RetrievedChunk


def _reference(chunk: RetrievedChunk) -> str:
    """Section-level reference inside a document."""
    if chunk.source_type == "pdf":  # location = "trang N"
        return f"{chunk.section_code}, {chunk.location}" if chunk.section_code else chunk.location
    if chunk.source_type in ("faq", "xlsx"):  # location carries the row ("…, dòng N" / "Sheet X, dòng N")
        return chunk.location
    return chunk.section_code or chunk.location


def format_sources(chunks: list[RetrievedChunk]) -> str:
    """Group cited chunks by document, keep citation order, drop duplicates."""
    groups: dict[str, list[str]] = {}
    files: dict[str, str | None] = {}
    for chunk in chunks:
        if chunk.filename is None:  # instructor-approved FAQ entry
            key, file = "FAQ đã duyệt", None
        else:
            key, file = (chunk.doc_code or chunk.filename), chunk.filename
        files.setdefault(key, file)
        refs = groups.setdefault(key, [])
        ref = _reference(chunk)
        if ref not in refs:
            refs.append(ref)
    parts = []
    for key, refs in groups.items():
        file, joined = files[key], "; ".join(refs)
        # instructor FAQ, or a document without code: "faq.xlsx (Sheet FAQ, dòng 3)"
        if file is None or key == file:
            parts.append(f"{key} ({joined})")
        else:  # "DOC-AUTO-01 – AUTO-03 (02_Giao_trinh_AI_Automation_n8n.docx)"
            parts.append(f"{key} – {joined} ({file})")
    return SOURCES_PREFIX + "; ".join(parts)
