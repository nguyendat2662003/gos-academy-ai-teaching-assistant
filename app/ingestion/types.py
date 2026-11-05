"""Parser output types (format-independent)."""

from dataclasses import dataclass, field


@dataclass
class Section:
    """A structural unit of a source document (a heading section, a PDF page piece, or one FAQ row)."""

    text: str
    location: str  # human readable: "AUTO-03 HTTP API, 401, 403 và 429", "trang 2", "Sheet FAQ, dòng 3"
    section_code: str | None = None  # e.g. "AUTO-03"; decides the scope (class) of the content
    title: str | None = None  # heading path, used as chunk context
    is_faq: bool = False


@dataclass
class ParsedDocument:
    filename: str
    source_type: str  # pdf | docx | xlsx
    title: str | None
    doc_code: str | None  # e.g. "DOC-AUTO-01" when the document declares one
    sections: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
