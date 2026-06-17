import pytest

from src.backend.app.rag.retriever import find_restricted, retrieve


async def _token(client) -> str:
    r = await client.post("/api/v1/auth/login", json={"code": "GV001", "password": "pass123"})
    return r.json()["token"]


@pytest.mark.asyncio
async def test_retrieve_permission(session_factory, seed_docs, patch_embeddings, requester):
    """Gác quyền ở tầng SQL: Public người khác ĐƯỢC, Private người khác KHÔNG."""
    async with session_factory() as db:
        contexts = await retrieve(db, "noi dung", requester)
        restricted = await find_restricted(db, requester)

    titles = [c["title"] for c in contexts]
    assert "Tai lieu PUBLIC" in titles
    assert "Tai lieu PRIVATE" not in titles

    restricted_files = [r["file"] for r in restricted]
    assert "Tai lieu PRIVATE" in restricted_files
    assert all(r["action"] == "request_access" for r in restricted)


@pytest.fixture
def patch_agent(monkeypatch):
    """Mock agent để không gọi OpenAI; trả citation tài liệu Public."""

    async def fake_run_agent(db, user, query):
        return "Cau tra loi mau", [
            {"title": "Tai lieu PUBLIC", "storage_uri": "memory://pub", "page_ref": "1", "content": "..."}
        ]

    monkeypatch.setattr("src.backend.app.api.v1.search.run_agent", fake_run_agent)


@pytest.mark.asyncio
async def test_search_route(client, seed_docs, patch_agent):
    token = await _token(client)
    r = await client.post(
        "/api/v1/search", json={"query": "noi dung"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["answer"] == "Cau tra loi mau"
    assert [c["file"] for c in data["citations"]] == ["Tai lieu PUBLIC"]
    # Private người khác hiện trong restricted (để xin quyền).
    assert "Tai lieu PRIVATE" in [x["file"] for x in data["restricted"]]


@pytest.mark.asyncio
async def test_search_requires_auth(client):
    r = await client.post("/api/v1/search", json={"query": "x"})
    assert r.status_code in (401, 403)
