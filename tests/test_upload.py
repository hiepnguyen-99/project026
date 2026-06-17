import pytest


async def _login(client) -> str:
    r = await client.post("/api/v1/auth/login", json={"code": "GV001", "password": "pass123"})
    return r.json()["token"]


@pytest.mark.asyncio
async def test_upload_success(client):
    token = await _login(client)
    files = {"file": ("test.pdf", b"%PDF-1.4 noi dung mau", "application/pdf")}
    r = await client.post(
        "/api/v1/documents", files=files, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "pending"
    assert data["document_id"]
    assert len(data["content_hash"]) == 64


@pytest.mark.asyncio
async def test_upload_duplicate(client):
    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = b"%PDF-1.4 file y het nhau"

    r1 = await client.post(
        "/api/v1/documents", files={"file": ("a.pdf", payload, "application/pdf")}, headers=headers
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/documents", files={"file": ("a.pdf", payload, "application/pdf")}, headers=headers
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    files = {"file": ("test.pdf", b"data", "application/pdf")}
    r = await client.post("/api/v1/documents", files=files)
    assert r.status_code in (401, 403)
