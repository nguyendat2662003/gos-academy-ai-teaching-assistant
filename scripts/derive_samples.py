"""Build format-converted copies of the sample material in data/derived/ (DECISIONS D-08).

The brief requires PDF, DOCX and XLSX/FAQ ingestion, but the HR sample set only contains DOCX. This script
converts — without changing any wording — so the PDF and XLSX parsers can be demonstrated on real content:

- data/derived/AUTO-N8N-01/02_Giao_trinh_AI_Automation_n8n.pdf
    exported by Microsoft Word (Windows, COM) or LibreOffice (`soffice --headless`), whichever exists.
- data/derived/COMMON/03_FAQ_bang_hoi_dap.xlsx
    the two "Câu hỏi | Trả lời mẫu" tables of 03_FAQ_...docx, one row per Q&A, plus the section code
    of the heading above each table (so rows can be scoped to the right class).

data/samples/ is only read. Derived files are NOT ingested by default (they duplicate the DOCX content).

Run: python scripts/derive_samples.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from docx import Document
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
DERIVED = ROOT / "data" / "derived"

PDF_SOURCE = SAMPLES / "AUTO-N8N-01" / "02_Giao_trinh_AI_Automation_n8n.docx"
FAQ_SOURCE = SAMPLES / "COMMON" / "03_FAQ_Quy_dinh_lop_hoc_GIA_LAP.docx"


def export_pdf(source: Path, target: Path) -> str:
    """Convert DOCX -> PDF with Word (COM) or LibreOffice. Returns the tool used."""
    target.parent.mkdir(parents=True, exist_ok=True)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run(  # noqa: S603 - fixed arguments, no user input
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(target.parent), str(source)],
            check=True,
        )
        (target.parent / f"{source.stem}.pdf").replace(target)
        return "libreoffice"
    if sys.platform == "win32":
        # wdExportFormatPDF = 17. Document opened read-only; Word quits even on error.
        ps = (
            "$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
            "try { $d = $w.Documents.Open($env:SRC, $false, $true); "
            "$d.ExportAsFixedFormat($env:DST, 17); $d.Close($false) } finally { $w.Quit() }"
        )
        subprocess.run(  # noqa: S603 - fixed command, paths passed via env
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],  # noqa: S607
            check=True,
            env={**os.environ, "SRC": str(source), "DST": str(target)},
        )
        return "word"
    raise RuntimeError("Need Microsoft Word (Windows) or LibreOffice (soffice) to export PDF")


def export_faq_xlsx(source: Path, target: Path) -> int:
    """Copy every 'Câu hỏi | Trả lời mẫu' table row into one sheet. Returns the number of rows."""
    doc = Document(str(source))
    body = doc.element.body
    current_code: str | None = None
    rows: list[tuple[str, str, str]] = []
    tables = iter(doc.tables)
    paragraphs = {p._p: p for p in doc.paragraphs}
    for element in body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = paragraphs.get(element)
            if para is not None and para.style.name.startswith("Heading") and para.text.strip():
                current_code = para.text.split()[0]
        elif tag == "tbl":
            table = next(tables)
            header = [c.text.strip() for c in table.rows[0].cells]
            if header[:2] != ["Câu hỏi", "Trả lời mẫu"]:
                continue
            for row in table.rows[1:]:
                question, answer = (c.text.strip() for c in row.cells[:2])
                rows.append((current_code or "", question, answer))

    wb = Workbook()
    ws = wb.active
    ws.title = "FAQ"
    ws.append(["Mã mục", "Câu hỏi", "Trả lời mẫu"])
    for r in rows:
        ws.append(list(r))
    target.parent.mkdir(parents=True, exist_ok=True)
    wb.save(target)
    return len(rows)


def main() -> None:
    pdf_target = DERIVED / "AUTO-N8N-01" / "02_Giao_trinh_AI_Automation_n8n.pdf"
    tool = export_pdf(PDF_SOURCE, pdf_target)
    print(f"PDF  ({tool}): {pdf_target.relative_to(ROOT)}")
    xlsx_target = DERIVED / "COMMON" / "03_FAQ_bang_hoi_dap.xlsx"
    n = export_faq_xlsx(FAQ_SOURCE, xlsx_target)
    print(f"XLSX ({n} rows): {xlsx_target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
