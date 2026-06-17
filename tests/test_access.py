import pytest


async def _token(client, code, password) -> str:
    r = await client.post("/api/v1/auth/login", json={"code": code, "password": password})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_access_request_flow(client, seed_docs):
    """Xin quyền → chủ duyệt → tải được; trước duyệt thì KHÔNG tải được."""
    priv_id = seed_docs["private_id"]
    gv = await _token(client, "GV001", "pass123")
    tbm = await _token(client, "TBM001", "tbm123")  # chủ tài liệu Private

    # 1. Trước khi xin: GV001 KHÔNG tải được tài liệu Private của người khác.
    r = await client.get(f"/api/v1/documents/{priv_id}/download", headers=_auth(gv))
    assert r.status_code == 403

    # 2. GV001 gửi yêu cầu xin quyền.
    r = await client.post(
        "/api/v1/access-requests", json={"document_id": priv_id}, headers=_auth(gv)
    )
    assert r.status_code == 201
    req_id = r.json()["id"]
    assert r.json()["status"] == "pending"

    # 3. Chủ tài liệu (TBM001) thấy yêu cầu đến.
    r = await client.get("/api/v1/access-requests", headers=_auth(tbm))
    assert req_id in [x["id"] for x in r.json()]

    # 4. Chủ duyệt.
    r = await client.patch(
        f"/api/v1/access-requests/{req_id}", json={"status": "approved"}, headers=_auth(tbm)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # 5. Sau khi duyệt: GV001 tải được.
    r = await client.get(f"/api/v1/documents/{priv_id}/download", headers=_auth(gv))
    assert r.status_code == 200
    assert r.json()["url"]


@pytest.mark.asyncio
async def test_decide_requires_owner(client, seed_docs):
    """Người không phải chủ/admin KHÔNG được duyệt yêu cầu."""
    priv_id = seed_docs["private_id"]
    gv = await _token(client, "GV001", "pass123")

    r = await client.post(
        "/api/v1/access-requests", json={"document_id": priv_id}, headers=_auth(gv)
    )
    req_id = r.json()["id"]

    # GV001 (người xin, không phải chủ) tự duyệt → 403.
    r = await client.patch(
        f"/api/v1/access-requests/{req_id}", json={"status": "approved"}, headers=_auth(gv)
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_set_permissions(client):
    """Chỉ quản trị mới đổi vai trò; giảng viên bị chặn."""
    qt = await _token(client, "QT001", "admin123")
    gv = await _token(client, "GV001", "pass123")

    # Admin đổi role GV001 → truong_bo_mon.
    r = await client.put(
        "/api/v1/admin/permissions",
        json={"code": "GV001", "role": "truong_bo_mon"},
        headers=_auth(qt),
    )
    assert r.status_code == 200
    assert r.json()["role"] == "truong_bo_mon"

    # Giảng viên thường không được dùng endpoint admin.
    r = await client.put(
        "/api/v1/admin/permissions",
        json={"code": "QT001", "role": "giang_vien"},
        headers=_auth(gv),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_confirm_sets_ready(client, seed_docs):
    """Chủ xác nhận metadata → status=ready."""
    priv_id = seed_docs["private_id"]
    tbm = await _token(client, "TBM001", "tbm123")
    r = await client.post(
        f"/api/v1/documents/{priv_id}/confirm",
        json={"topic": "Toan", "doc_type": "giao_trinh"},
        headers=_auth(tbm),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
