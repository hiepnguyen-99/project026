import io

from minio import Minio

from ..core.config import settings


class Storage:
    """Interface lưu trữ object — cho phép thay thế khi test."""

    def put_object(self, object_name: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    def get_object(self, uri: str) -> bytes:
        raise NotImplementedError

    def get_presigned_url(self, uri: str) -> str:
        raise NotImplementedError


class MinioStorage(Storage):
    def __init__(self) -> None:
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put_object(self, object_name: str, data: bytes, content_type: str) -> str:
        self.client.put_object(
            self.bucket,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return f"minio://{self.bucket}/{object_name}"

    def get_object(self, uri: str) -> bytes:
        object_name = uri.split(f"minio://{self.bucket}/", 1)[-1]
        resp = self.client.get_object(self.bucket, object_name)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def get_presigned_url(self, uri: str) -> str:
        object_name = uri.split(f"minio://{self.bucket}/", 1)[-1]
        return self.client.presigned_get_object(self.bucket, object_name)


_storage: Storage | None = None


def get_storage() -> Storage:
    """FastAPI dependency — singleton MinioStorage (override khi test)."""
    global _storage
    if _storage is None:
        _storage = MinioStorage()
    return _storage
