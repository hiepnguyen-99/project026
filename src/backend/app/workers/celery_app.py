from celery import Celery

from ..core.config import settings

celery_app = Celery(
    "eduvault",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)


@celery_app.task(name="ingest_document")
def ingest_document(document_id: str) -> dict:
    """Tải file → parse → chunk → embed → ghi pgvector (logic trong workers/ingest.py)."""
    from .ingest import run_ingest

    run_ingest(document_id)
    return {"document_id": document_id, "status": "done"}
