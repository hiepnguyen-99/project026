import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import src.backend.app.api.v1.documents as documents_module
from src.backend.app.core.security import hash_password
from src.backend.app.db.base import Base
from src.backend.app.db.session import get_db
from src.backend.app.main import app
from src.backend.app.models import access_request as _ar  # noqa: F401  (đăng ký bảng)
from src.backend.app.models import chunk as _chunk  # noqa: F401  (đăng ký bảng)
from src.backend.app.models import document as _document  # noqa: F401  (đăng ký bảng)
from src.backend.app.models.user import User, UserRole
from src.backend.app.services.storage import Storage, get_storage

# Test dùng SQLite in-memory (StaticPool để app + test chia sẻ cùng 1 connection).
TEST_DB_URL = "sqlite+aiosqlite://"


class _NoopTask:
    """Thay ingest_document.delay — không gọi Redis broker khi test API."""

    def delay(self, *args, **kwargs):
        return None


documents_module.ingest_document = _NoopTask()


class FakeStorage(Storage):
    """Lưu object trong RAM thay cho MinIO khi test."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def _name(self, uri: str) -> str:
        return uri.replace("memory://", "", 1)

    def put_object(self, object_name: str, data: bytes, content_type: str) -> str:
        self.objects[object_name] = data
        return f"memory://{object_name}"

    def get_object(self, uri: str) -> bytes:
        return self.objects[self._name(uri)]

    def get_presigned_url(self, uri: str) -> str:
        return f"http://test/{uri}"


@pytest.fixture
async def engine():
    eng = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def client(session_factory):
    # Seed 2 user mẫu cho test.
    async with session_factory() as s:
        s.add_all(
            [
                User(
                    code="GV001",
                    full_name="Giang Vien A",
                    hashed_password=hash_password("pass123"),
                    role=UserRole.giang_vien,
                ),
                User(
                    code="QT001",
                    full_name="Quan Tri",
                    hashed_password=hash_password("admin123"),
                    role=UserRole.quan_tri,
                ),
                User(
                    code="TBM001",
                    full_name="Truong Bo Mon",
                    hashed_password=hash_password("tbm123"),
                    role=UserRole.truong_bo_mon,
                ),
            ]
        )
        await s.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def seed_docs(session_factory):
    """2 tài liệu của người KHÁC (TBM001): 1 public, 1 private — để test gác quyền."""
    from src.backend.app.models.chunk import Chunk
    from src.backend.app.models.document import DocStatus, Document, Visibility

    async with session_factory() as s:
        pub = Document(
            owner_code="TBM001",
            title="Tai lieu PUBLIC",
            visibility=Visibility.public,
            storage_uri="memory://pub",
            content_hash="hash_pub",
            status=DocStatus.ready,
        )
        priv = Document(
            owner_code="TBM001",
            title="Tai lieu PRIVATE",
            visibility=Visibility.private,
            storage_uri="memory://priv",
            content_hash="hash_priv",
            status=DocStatus.ready,
        )
        s.add_all([pub, priv])
        await s.flush()
        s.add_all(
            [
                Chunk(document_id=pub.id, content="noi dung cong khai", page_ref="1", embedding=[0.1, 0.2, 0.3]),
                Chunk(document_id=priv.id, content="noi dung rieng tu", page_ref="1", embedding=[0.4, 0.5, 0.6]),
            ]
        )
        await s.commit()
        return {"public_id": str(pub.id), "private_id": str(priv.id)}


@pytest.fixture
def patch_embeddings(monkeypatch):
    """Tránh gọi OpenAI embeddings thật khi test."""
    monkeypatch.setattr(
        "src.backend.app.rag.embeddings.embed_texts",
        lambda texts: [[0.0, 0.0, 0.0] for _ in texts],
    )


@pytest.fixture
def requester():
    """User giảng viên GV001 (in-memory, đủ cho retrieve/tools — chỉ cần .code)."""
    return User(
        code="GV001",
        full_name="Giang Vien A",
        hashed_password="x",
        role=UserRole.giang_vien,
    )
