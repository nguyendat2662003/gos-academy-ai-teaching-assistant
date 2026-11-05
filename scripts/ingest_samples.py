"""Ingest the sample material: every supported file in data/samples/<SCOPE>/ (folders starting with "_" are
skipped). The folder name is the upload scope: a class id, or COMMON for files mixing several scopes.

Uses EMBEDDING_PROVIDER from the environment. Run inside the stack (DB host = "postgres"):
  docker compose exec api python scripts/ingest_samples.py [--include-derived] [--force]

Prints one line per (file, scope), then per-class totals of ACTIVE chunks.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.classes import get_registry  # noqa: E402
from app.db.models import Chunk, Document, DocumentStatus  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.ingestion.indexer import IngestError, index_file  # noqa: E402
from app.ingestion.parsers import SUPPORTED_SUFFIXES  # noqa: E402
from app.providers.registry import get_embedding_provider  # noqa: E402

ROOTS = {"samples": Path("data/samples"), "derived": Path("data/derived")}


def discover(include_derived: bool) -> list[tuple[str, Path]]:
    roots = [ROOTS["samples"]] + ([ROOTS["derived"]] if include_derived else [])
    files = []
    for root in roots:
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
            for path in sorted(folder.iterdir()):
                # "~$x.docx" = Word/Excel lock file of an open document, ".x" = hidden: not material
                if path.suffix.lower() in SUPPORTED_SUFFIXES and not path.name.startswith(("~$", ".")):
                    files.append((folder.name, path))
    return files


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-derived", action="store_true", help="also index data/derived (duplicates!)"
    )
    parser.add_argument("--force", action="store_true", help="re-embed even unchanged content")
    args = parser.parse_args()

    registry = get_registry()
    embedder = get_embedding_provider()
    print(f"embedding: provider={embedder.name} model={embedder.model} dim={embedder.dim}\n")

    total_tokens = 0
    warnings = 0
    flagged = 0
    async with get_sessionmaker()() as session:
        for scope, path in discover(args.include_derived):
            try:
                report = await index_file(
                    session,
                    data=path.read_bytes(),
                    filename=path.name,
                    origin_scope=scope,
                    embedder=embedder,
                    registry=registry,
                    force=args.force,
                )
            except IngestError as exc:
                print(f"[REFUSED] {path}: {exc}")
                continue
            warnings += len(report.warnings)
            for w in report.warnings:
                print(f"  ! {path.name}: {w}")
            for r in report.results:
                total_tokens += r.embedding_tokens
                flagged += r.flagged
                print(
                    f"{r.status:<10} {path.name:<48} -> {r.scope:<12} v{r.version} "
                    f"chunks={r.chunks:<3} flagged={r.flagged} emb_tokens={r.embedding_tokens}"
                    + (f" error={r.error}" if r.error else "")
                )

        rows = await session.execute(
            select(Chunk.class_id, func.count(Chunk.id), func.count(func.distinct(Chunk.document_id)))
            .join(Document, Document.id == Chunk.document_id)
            .where(Document.status == DocumentStatus.ACTIVE)
            .group_by(Chunk.class_id)
            .order_by(Chunk.class_id)
        )
        print("\nACTIVE knowledge base per scope")
        print(f"{'scope':<14}{'documents':>10}{'chunks':>8}")
        for class_id, chunks, docs in rows.all():
            print(f"{class_id:<14}{docs:>10}{chunks:>8}")
    print(f"\nthis run: embedding_tokens={total_tokens} parser_warnings={warnings} flagged_chunks={flagged}")
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
