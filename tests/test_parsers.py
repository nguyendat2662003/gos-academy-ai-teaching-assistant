"""Parsers on the real sample material (read-only) and on synthetic fixtures."""

from pathlib import Path

import pytest

from app.ingestion.chunker import chunk_document, split_section
from app.ingestion.parsers import parse_file
from app.ingestion.text import estimate_tokens, fold, scope_prefix, split_heading

SAMPLES = Path("data/samples")
DERIVED = Path("data/derived")
FIXTURES = Path("tests/fixtures")

GS_DOCX = SAMPLES / "GS-KPI-01" / "01_Giao_trinh_Google_Sheets_KPI_Dashboard.docx"
AUTO_DOCX = SAMPLES / "AUTO-N8N-01" / "02_Giao_trinh_AI_Automation_n8n.docx"
FAQ_DOCX = SAMPLES / "COMMON" / "03_FAQ_Quy_dinh_lop_hoc_GIA_LAP.docx"
AUTO_PDF = DERIVED / "AUTO-N8N-01" / "02_Giao_trinh_AI_Automation_n8n.pdf"
FAQ_XLSX = DERIVED / "COMMON" / "03_FAQ_bang_hoi_dap.xlsx"


def test_split_heading_and_scope() -> None:
    assert split_heading("AUTO-CLASS-02  Câu hỏi thường gặp") == ("AUTO-CLASS-02", "Câu hỏi thường gặp")
    assert split_heading("Giới thiệu chung") == (None, "Giới thiệu chung")
    assert scope_prefix("AUTO-CLASS-02") == "AUTO"
    assert scope_prefix("COMMON-03") == "COMMON"
    assert fold("Bỏ QUA Hướng Dẫn đã") == "bo qua huong dan da"


def test_docx_gs_sections_codes_and_formulas_verbatim() -> None:
    doc = parse_file(GS_DOCX)
    assert doc.doc_code == "DOC-GS-01"
    assert [s.section_code for s in doc.sections] == [f"GS-0{i}" for i in range(1, 9)]
    gs02 = next(s for s in doc.sections if s.section_code == "GS-02")
    formula = (
        '=SUMIFS(Data!$D$2:$D;Data!$A$2:$A;">="&$B$1;Data!$A$2:$A;"<"&($B$2+1);Data!$E$2:$E;"Thành công")'
    )
    assert formula in gs02.text
    gs01 = doc.sections[0]
    assert "D – Doanh thu: 1.200.000" in gs01.text  # table -> text rows
    assert not doc.warnings


def test_docx_preamble_and_headers_not_indexed() -> None:
    doc = parse_file(AUTO_DOCX)
    text = "\n".join(s.text for s in doc.sections)
    assert "LƯU Ý: Nội dung" not in text and "Mã tài liệu" not in text
    assert len(doc.sections) == 10


def test_docx_faq_tables_become_rows_with_section_codes() -> None:
    doc = parse_file(FAQ_DOCX)
    assert doc.doc_code == "DOC-FAQ-01"
    faq = [s for s in doc.sections if s.is_faq]
    assert len(faq) == 8
    assert {s.section_code for s in faq} == {"GS-CLASS-02", "AUTO-CLASS-02"}
    gs_deadline = next(s for s in faq if s.section_code == "GS-CLASS-02" and "nộp khi nào" in s.text)
    assert "Chủ nhật" in gs_deadline.text and gs_deadline.location == "GS-CLASS-02, dòng 4"
    codes = {s.section_code for s in doc.sections if not s.is_faq}
    assert {"COMMON-01", "COMMON-02", "COMMON-03", "COMMON-04", "GS-CLASS-01", "AUTO-CLASS-01"} <= codes


def test_pdf_pages_codes_and_no_header_footer() -> None:
    doc = parse_file(AUTO_PDF)
    assert doc.doc_code == "DOC-AUTO-01"
    assert [s.section_code for s in doc.sections] == [f"AUTO-{i:02d}" for i in range(1, 11)]
    assert {s.location for s in doc.sections} <= {"trang 1", "trang 2"}
    joined = "\n".join(s.text for s in doc.sections)
    assert "BỘ DỮ LIỆU TEST" not in joined and "" not in joined


def test_pdf_empty_page_is_reported_not_silently_skipped() -> None:
    doc = parse_file(FIXTURES / "scanned_like.pdf")
    assert len(doc.sections) == 1
    assert doc.warnings == ["trang 2: không có text (có thể là ảnh scan) — chưa được index"]


def test_xlsx_rows_locations_and_section_column() -> None:
    doc = parse_file(FAQ_XLSX)
    assert len(doc.sections) == 8
    first = doc.sections[0]
    assert first.location == "Sheet FAQ, dòng 2" and first.section_code == "GS-CLASS-02" and first.is_faq


def test_xlsx_custom_headers_and_incomplete_row_warning() -> None:
    doc = parse_file(FIXTURES / "faq_custom_headers.xlsx")
    assert [s.location for s in doc.sections] == ["Sheet Hoi dap, dòng 2", "Sheet Hoi dap, dòng 4"]
    assert doc.warnings == ["Sheet Hoi dap, dòng 3: thiếu câu hỏi hoặc trả lời — bỏ qua"]


def test_unsupported_extension() -> None:
    with pytest.raises(ValueError):
        parse_file(Path("notes.txt"))


# ------------------------------------------------------------------ chunker


def test_each_sample_section_is_one_chunk_with_context_line() -> None:
    doc = parse_file(GS_DOCX)
    chunks = chunk_document(doc)
    assert len(chunks) == len(doc.sections)
    assert chunks[1].content.startswith("[Tài liệu: DOC-GS-01 – 01 | GIÁO TRÌNH MẪU")
    assert "Mục: GS-02 SUMIFS và COUNTIFS theo khoảng ngày]" in chunks[1].content.splitlines()[0]


def test_long_section_split_on_sentences_with_overlap() -> None:
    sentences = [f"Câu số {i} mô tả một bước cấu hình workflow n8n khá chi tiết." for i in range(120)]
    text = " ".join(sentences)
    pieces = split_section(text, max_tokens=800, target_tokens=600, overlap_ratio=0.12)
    assert len(pieces) > 1
    assert all(estimate_tokens(p) <= 600 + 30 for p in pieces)
    for prev, nxt in zip(pieces, pieces[1:], strict=False):
        assert prev.split(". ")[-1].rstrip(".") in nxt  # last sentence carried over
    for p in pieces:  # never cut inside a sentence
        assert p.endswith(".")


def test_short_section_not_split() -> None:
    assert split_section("Một câu ngắn.", 800, 600, 0.12) == ["Một câu ngắn."]
