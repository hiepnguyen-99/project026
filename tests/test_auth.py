import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    resp = await client.post("/api/v1/auth/login", json={"code": "GV001", "password": "pass123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"]
    assert data["user"]["code"] == "GV001"
    assert data["role"] == "giang_vien"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/api/v1/auth/login", json={"code": "GV001", "password": "sai"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_code(client):
    resp = await client.post("/api/v1/auth/login", json={"code": "KHONGCO", "password": "x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_with_token(client):
    login = await client.post("/api/v1/auth/login", json={"code": "GV001", "password": "pass123"})
    token = login.json()["token"]
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["code"] == "GV001"


@pytest.mark.asyncio
async def test_rbac_blocks_wrong_role(client):
    login = await client.post("/api/v1/auth/login", json={"code": "GV001", "password": "pass123"})
    token = login.json()["token"]
    resp = await client.get("/api/v1/auth/admin-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_rbac_allows_admin(client):
    login = await client.post("/api/v1/auth/login", json={"code": "QT001", "password": "admin123"})
    token = login.json()["token"]
    resp = await client.get("/api/v1/auth/admin-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
