"""Parse + chunk files and print the first chunks (quality check before indexing). No DB, no API calls.

Run: python scripts/preview_chunks.py [FILE ...] [--first 5]
     (no FILE = every supported file in data/samples/<scope>/ and data/derived/<scope>/)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.chunker import chunk_document  # noqa: E402
from app.ingestion.parsers import SUPPORTED_SUFFIXES, parse_file  # noqa: E402

DEFAULT_ROOTS = (Path("data/samples"), Path("data/derived"))


def default_files() -> list[Path]:
    return sorted(
        p
        for root in DEFAULT_ROOTS
        for p in root.glob("*/*")
        if p.suffix.lower() in SUPPORTED_SUFFIXES and not p.parent.name.startswith("_")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--first", type=int, default=5)
    args = parser.parse_args()

    for path in args.files or default_files():
        doc = parse_file(path)
        chunks = chunk_document(doc)
        tokens = [c.token_count for c in chunks] or [0]
        avg = sum(tokens) // len(tokens)
        print("=" * 100)
        print(f"{path}  [{doc.source_type}]  doc_code={doc.doc_code}  title={doc.title!r}")
        print(
            f"sections={len(doc.sections)} chunks={len(chunks)} "
            f"tokens(min/avg/max)={min(tokens)}/{avg}/{max(tokens)} "
            f"flagged={sum(c.flagged_injection for c in chunks)} warnings={doc.warnings}"
        )
        for i, c in enumerate(chunks[: args.first], start=1):
            print(f"--- #{i} code={c.section_code} faq={c.is_faq} ~{c.token_count} tok | {c.location}")
            print(c.content)


if __name__ == "__main__":
    main()
