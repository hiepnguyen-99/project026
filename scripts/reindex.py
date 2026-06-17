"""Chạy lại ingestion cho 1 document. Dùng: python scripts/reindex.py <document_id>"""
import asyncio
import sys

from src.backend.app.workers.ingest import _run_ingest

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reindex.py <document_id>")
        sys.exit(1)
    asyncio.run(_run_ingest(sys.argv[1]))
    print(f"[reindex] Xong document {sys.argv[1]}")
