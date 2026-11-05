"""Format parsers: DOCX (headings), PDF (pages), XLSX (one Q&A per row) -> ParsedDocument.

Parsers never decide the class of the content; they only extract section codes (see indexer/scoping).
"""

import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path

import pymupdf
from docx import Document as load_docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook

from app.core.config import get_settings
from app.ingestion.text import DOC_CODE_RE, clean, fold, split_heading
from app.ingestion.types import ParsedDocument, Section

SUPPORTED_SUFFIXES = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx"}

# Header/footer bands of a PDF page (fraction of page height) that are repeated on every page.
_PDF_MARGIN = 0.07


def parse_file(path: Path) -> ParsedDocument:
    """Dispatch on the file extension."""
    kind = SUPPORTED_SUFFIXES.get(path.suffix.lower())
    if kind == "docx":
        return parse_docx(path)
    if kind == "pdf":
        return parse_pdf(path)
    if kind == "xlsx":
        return parse_xlsx(path)
    raise ValueError(f"unsupported file type: {path.suffix}")


# ------------------------------------------------------------------ FAQ column matching


def _match_column(headers: list[str], candidates: Iterable[str]) -> int | None:
    folded = [fold(h).strip() for h in headers]
    for candidate in candidates:
        c = fold(candidate).strip()
        if c in folded:
            return folded.index(c)
    return None


def _faq_columns(headers: list[str]) -> tuple[int, int, int | None] | None:
    s = get_settings()
    q = _match_column(headers, s.faq_question_columns)
    a = _match_column(headers, s.faq_answer_columns)
    if q is None or a is None or q == a:
        return None
    return q, a, _match_column(headers, s.faq_section_columns)


def _faq_text(question: str, answer: str) -> str:
    return f"Hỏi: {question}\nĐáp: {answer}"


# ------------------------------------------------------------------ DOCX


def _iter_blocks(doc: DocxDocument) -> Iterator[Paragraph | Table]:
    """Paragraphs and tables of the body in document order (headers/footers excluded)."""
    for element in doc.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(element, doc)
        elif tag == "tbl":
            yield Table(element, doc)


class _DocxSectionBuilder:
    """Accumulates body lines under the current heading and emits Sections."""

    def __init__(self) -> None:
        self.sections: list[Section] = []
        self.path: list[str] = []  # heading texts by level
        self.code: str | None = None
        self.heading: str | None = None
        self.lines: list[str] = []
        self.list_counter = 0

    def start(self, level: int, text: str) -> None:
        self.flush()
        self.path = self.path[: level - 1] + [text]
        code, _ = split_heading(text)
        if code or level == 1:
            self.code = code  # an uncoded sub-heading keeps its parent's code
        self.heading = text
        self.list_counter = 0

    def add_line(self, line: str) -> None:
        self.lines.append(line)

    def add_faq(self, row_no: int, question: str, answer: str, code: str | None) -> None:
        section_code = code or self.code
        where = section_code or (self.heading or "FAQ")
        self.sections.append(
            Section(
                text=_faq_text(question, answer),
                location=f"{where}, dòng {row_no}",
                section_code=section_code,
                title=" > ".join(self.path) or None,
                is_faq=True,
            )
        )

    def flush(self) -> None:
        body = clean("\n".join(self.lines))
        if body and self.heading:
            self.sections.append(
                Section(
                    text=body,
                    location=" ".join(self.heading.split()),
                    section_code=self.code,
                    title=" > ".join(self.path),
                )
            )
        self.lines = []


def parse_docx(path: Path) -> ParsedDocument:
    doc = load_docx(str(path))
    result = ParsedDocument(filename=path.name, source_type="docx", title=None, doc_code=None)
    builder = _DocxSectionBuilder()

    for block in _iter_blocks(doc):
        if isinstance(block, Table):
            _docx_table(block, builder, result)
            continue
        text = block.text.strip()
        if not text:
            continue
        style = block.style.style_id if block.style is not None else ""
        if result.doc_code is None and (m := DOC_CODE_RE.search(text)):
            result.doc_code = m.group("code")
        if style == "Title":
            result.title = text
        elif style.startswith("Heading"):
            level = int(style.removeprefix("Heading") or 1)
            builder.start(level, text)
        elif builder.heading is None:
            continue  # preamble (document code, disclaimer) is metadata, not indexed
        elif style == "ListBullet":
            builder.add_line(f"- {text}")
        elif style == "ListNumber":
            builder.list_counter += 1
            builder.add_line(f"{builder.list_counter}. {text}")
        else:
            builder.add_line(text)  # includes CodeContent: kept verbatim (formulas, ; $ ")
    builder.flush()

    result.sections = builder.sections
    if not result.sections:
        result.warnings.append("không tìm thấy mục nào có heading — tài liệu chưa được index")
    return result


def _docx_table(table: Table, builder: _DocxSectionBuilder, result: ParsedDocument) -> None:
    rows = [[" ".join(c.text.split()) for c in row.cells] for row in table.rows]
    if not rows:
        return
    header, data = rows[0], rows[1:]
    columns = _faq_columns(header)
    if columns:
        q, a, s = columns
        for i, row in enumerate(data, start=1):
            if not row[q] or not row[a]:
                result.warnings.append(
                    f"{builder.code or 'bảng'} dòng {i}: thiếu câu hỏi hoặc trả lời — bỏ qua"
                )
                continue
            builder.add_faq(i, row[q], row[a], row[s] if s is not None and row[s] else None)
        return
    # Generic table -> one line per row: "Header: value | Header: value"
    for row in data:
        builder.add_line(" | ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False) if v))


# ------------------------------------------------------------------ PDF


def _pdf_page_blocks(page: pymupdf.Page) -> list[str]:
    """Text blocks of a page in reading order, minus the repeated header/footer bands; lines re-joined."""
    height = page.rect.height
    blocks = []
    for _x0, y0, _x1, y1, text, _no, kind in page.get_text("blocks", sort=True):
        if kind != 0 or y1 <= height * _PDF_MARGIN or y0 >= height * (1 - _PDF_MARGIN):
            continue
        # Word exports list bullets as Private-Use glyphs (e.g. U+F0B7): normalise them to "•".
        text = "".join("•" if unicodedata.category(ch) == "Co" else ch for ch in text)
        joined = " ".join(text.split())
        if joined:
            blocks.append(joined)
    return blocks


def _pdf_heading_code(block: str) -> str | None:
    code, _ = split_heading(block)
    return code if code and len(block) < 120 else None


def parse_pdf(path: Path) -> ParsedDocument:
    """One Section per (section code, page). PDFs without section codes give one Section per page."""
    result = ParsedDocument(filename=path.name, source_type="pdf", title=None, doc_code=None)
    with pymupdf.open(str(path)) as pdf:
        result.title = (pdf.metadata or {}).get("title") or None
        pages = [_pdf_page_blocks(page) for page in pdf]

    coded = any(_pdf_heading_code(b) for blocks in pages for b in blocks)
    code: str | None = None
    in_body = not coded  # coded documents: skip the preamble before the first heading

    for page_no, blocks in enumerate(pages, start=1):
        if not blocks:
            result.warnings.append(f"trang {page_no}: không có text (có thể là ảnh scan) — chưa được index")
            continue
        lines: list[str] = []
        for block in blocks:
            if result.doc_code is None and (m := DOC_CODE_RE.search(block)):
                result.doc_code = m.group("code")
            heading = _pdf_heading_code(block)
            if heading:
                _emit_pdf_section(result, lines, code, page_no, in_body)
                lines = []
                code, in_body = heading, True
            lines.append(block)
        _emit_pdf_section(result, lines, code, page_no, in_body)
    return result


def _emit_pdf_section(
    result: ParsedDocument, lines: list[str], code: str | None, page_no: int, in_body: bool
) -> None:
    body = clean("\n".join(lines))
    if body and in_body:
        result.sections.append(Section(text=body, location=f"trang {page_no}", section_code=code, title=code))


# ------------------------------------------------------------------ XLSX


def parse_xlsx(path: Path) -> ParsedDocument:
    result = ParsedDocument(filename=path.name, source_type="xlsx", title=path.stem, doc_code=None)
    wb = load_workbook(str(path), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header_row_no, header = _first_non_empty(rows)
            if header is None:
                continue
            columns = _faq_columns(header)
            if columns is None:
                result.warnings.append(f"Sheet {ws.title}: không thấy cột câu hỏi/câu trả lời — bỏ qua sheet")
                continue
            q, a, s = columns
            for row_no, values in enumerate(rows, start=header_row_no + 1):
                cells = ["" if v is None else " ".join(str(v).split()) for v in values]
                cells += [""] * (max(q, a, s or 0) + 1 - len(cells))
                if not any(cells):
                    continue
                if not cells[q] or not cells[a]:
                    result.warnings.append(
                        f"Sheet {ws.title}, dòng {row_no}: thiếu câu hỏi hoặc trả lời — bỏ qua"
                    )
                    continue
                result.sections.append(
                    Section(
                        text=_faq_text(cells[q], cells[a]),
                        location=f"Sheet {ws.title}, dòng {row_no}",
                        section_code=(cells[s] or None) if s is not None else None,
                        title=f"Sheet {ws.title}",
                        is_faq=True,
                    )
                )
    finally:
        wb.close()
    return result


def _first_non_empty(rows: Iterator[tuple]) -> tuple[int, list[str] | None]:
    for row_no, values in enumerate(rows, start=1):
        cells = ["" if v is None else str(v).strip() for v in values]
        if any(cells):
            return row_no, cells
    return 0, None
