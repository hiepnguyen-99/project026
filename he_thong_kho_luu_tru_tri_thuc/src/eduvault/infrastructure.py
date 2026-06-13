from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from . import database


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def object_storage_status() -> dict:
    configured = _enabled("MINIO_ENABLED")
    if not configured:
        return {"provider": "local-fallback", "configured": False, "available": True}
    try:
        client = _minio_client()
        client.bucket_exists(os.getenv("MINIO_BUCKET", "eduvault"))
        return {"provider": "minio", "configured": True, "available": True}
    except Exception as exc:
        return {"provider": "minio", "configured": True, "available": False, "detail": str(exc)}


def vector_store_status() -> dict:
    configured = _enabled("QDRANT_ENABLED")
    if not configured:
        return {"provider": "mysql-sqlite-fallback", "configured": False, "available": True}
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=2)
        client.get_collections()
        return {"provider": "qdrant", "configured": True, "available": True}
    except Exception as exc:
        return {"provider": "qdrant", "configured": True, "available": False, "detail": str(exc)}


def queue_status() -> dict:
    configured = _enabled("REDIS_ENABLED")
    if not configured:
        return {"provider": "database-outbox-sync", "configured": False, "available": True}
    try:
        import redis

        client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), socket_timeout=2)
        client.ping()
        return {"provider": "redis", "configured": True, "available": True}
    except Exception as exc:
        return {"provider": "redis", "configured": True, "available": False, "detail": str(exc)}


def infrastructure_status() -> dict:
    services = {
        "object_storage": object_storage_status(),
        "vector_store": vector_store_status(),
        "queue": queue_status(),
    }
    return {
        "architecture": "v2-hybrid",
        "database": database.database_backend(),
        "services": services,
        "ready": all(item["available"] for item in services.values()),
        "rpo_target_minutes": 60,
        "rto_target_hours": 4,
    }


def store_object(object_key: str, raw: bytes, content_type: str = "application/octet-stream") -> dict:
    checksum = hashlib.sha256(raw).hexdigest()
    if _enabled("MINIO_ENABLED"):
        try:
            from io import BytesIO

            client = _minio_client()
            bucket = os.getenv("MINIO_BUCKET", "eduvault")
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
            result = client.put_object(bucket, object_key, BytesIO(raw), len(raw), content_type=content_type)
            return {
                "provider": "minio",
                "object_uri": f"minio://{bucket}/{object_key}",
                "object_version": result.version_id or "",
                "checksum": checksum,
            }
        except Exception:
            # The demo remains usable when optional infrastructure is offline.
            pass

    path = database.STORAGE_DIR / "object-store" / Path(object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "provider": "local-fallback",
        "object_uri": f"local://{path.resolve()}",
        "object_version": "",
        "checksum": checksum,
    }


def delete_object(object_uri: str) -> None:
    if object_uri.startswith("local://"):
        path = Path(object_uri.removeprefix("local://"))
        if path.exists() and path.is_file():
            path.unlink()
        return
    if object_uri.startswith("minio://"):
        location = object_uri.removeprefix("minio://")
        bucket, object_key = location.split("/", 1)
        _minio_client().remove_object(bucket, object_key)


def upsert_vector(chunk_id: str, vector: list[float], payload: dict) -> bool:
    if not _enabled("QDRANT_ENABLED"):
        return False
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=5)
        collection = f"{os.getenv('QDRANT_COLLECTION', 'eduvault_chunks')}_{len(vector)}"
        existing = {item.name for item in client.get_collections().collections}
        if collection not in existing:
            client.create_collection(collection, vectors_config=VectorParams(size=len(vector), distance=Distance.COSINE))
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"eduvault:{chunk_id}"))
        client.upsert(collection, [PointStruct(id=point_id, vector=vector, payload={**payload, "chunk_id": chunk_id})])
        return True
    except Exception:
        return False


def delete_vectors(document_id: str) -> None:
    if not _enabled("QDRANT_ENABLED"):
        return
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=5)
        prefix = os.getenv("QDRANT_COLLECTION", "eduvault_chunks")
        for collection in client.get_collections().collections:
            if collection.name == prefix or collection.name.startswith(f"{prefix}_"):
                client.delete(
                    collection.name,
                    points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]),
                )
    except Exception:
        pass


def publish_event(event: dict) -> bool:
    if not _enabled("REDIS_ENABLED"):
        return False
    try:
        import json
        import redis

        client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), socket_timeout=2)
        client.rpush(os.getenv("REDIS_QUEUE", "eduvault:v2:jobs"), json.dumps(event, ensure_ascii=False))
        return True
    except Exception:
        return False


def _minio_client():
    from minio import Minio

    return Minio(
        os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "eduvault"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "eduvault-demo-secret"),
        secure=_enabled("MINIO_SECURE"),
    )
