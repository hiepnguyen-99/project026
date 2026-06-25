import tempfile
import zipfile
import os
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.eduvault import database, main as main_module, services
from src.eduvault.ai import ai_provider
from src.eduvault.main import app


def configure_temp_storage(root: Path):
    os.environ["DATABASE_PROVIDER"] = "sqlite"
    ai_provider.api_key = ""
    database.DATA_DIR = root
    database.DB_PATH = root / "eduvault.db"
    database.STORAGE_DIR = root / "storage"
    database.BACKUP_DIR = root / "backups"
    services.DB_PATH = database.DB_PATH
    services.STORAGE_DIR = database.STORAGE_DIR
    services.BACKUP_DIR = database.BACKUP_DIR
    database.init_database()


def login(client: TestClient, code: str) -> dict:
    password = os.environ[f"EDUVAULT_SEED_PASSWORD_{code.upper()}"]
    response = client.post("/api/auth/login", json={"code": code, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def assign_lecturer_csv(client: TestClient, admin_headers: dict, rows: list[tuple[str, str, str]]) -> dict:
    content = "lecturer_code,lecturer_name,specialization\n" + "\n".join(",".join(row) for row in rows)
    preview = client.post(
        "/api/lecturer-assignments/import/preview",
        headers={**admin_headers, "X-Filename": "assignments.csv", "Content-Type": "text/csv"},
        content=content.encode("utf-8"),
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        "/api/lecturer-assignments/import/confirm",
        headers=admin_headers,
        json={"batch_preview_id": preview.json()["batch_preview_id"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def activate_sample_policy(client: TestClient, admin_headers: dict) -> dict:
    policy_payload = {
        "faculty": "Khoa CNTT",
        "specializations": [
            {
                "name": "Tri tue nhan tao",
                "code": "AI",
                "courses": [
                    {"name": "AI Application", "standard_folders": ["De cuong", "Bai giang", "Lab", "De thi"]},
                    {"name": "Machine Learning", "standard_folders": ["De cuong", "Bai giang", "Lab", "De thi"]},
                ],
            },
            {
                "name": "Data Science",
                "code": "DS",
                "courses": [
                    {"name": "Data Mining", "standard_folders": ["De cuong", "Bai giang", "Lab", "De thi"]},
                ],
            },
        ],
    }
    uploaded = client.post(
        "/api/policies/upload",
        headers={**admin_headers, "X-Filename": "policy.json", "X-Title": "Policy Assignment Test", "Content-Type": "application/json"},
        content=json.dumps(policy_payload).encode("utf-8"),
    )
    assert uploaded.status_code == 201, uploaded.text
    activated = client.post(f"/api/policies/{uploaded.json()['id']}/activate", headers=admin_headers)
    assert activated.status_code == 200, activated.text
    return activated.json()


def seed_knowledge_transfer_insight_data(client: TestClient, admin_headers: dict) -> None:
    activate_sample_policy(client, admin_headers)
    assign_lecturer_csv(client, admin_headers, [("GV001", "Nguyen Van A", "AI")])
    with database.transaction() as db:
        ai_spec = db.execute("SELECT * FROM specializations WHERE name='Tri tue nhan tao'").fetchone()
        ml_course = db.execute(
            "SELECT * FROM folder_nodes WHERE parent_id=? AND type='course' AND name='Machine Learning' AND status='active'",
            (ai_spec["folder_node_id"],),
        ).fetchone()
        folder = db.execute(
            "SELECT * FROM folder_nodes WHERE parent_id=? AND type='standard_folder' AND name='De cuong' AND status='active'",
            (ml_course["id"],),
        ).fetchone()
        timestamp = database.now()
        db.execute(
            """INSERT INTO documents(id,title,doc_type,topic,owner_code,visibility,current_version,content_hash,
               created_at,updated_at,folder_path,folder_node_id,status,specialization_id,course_id,document_type)
               VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)""",
            (
                "doc-kt-ai-outline", "Machine Learning De cuong", "De cuong", "Machine Learning",
                "GV001", "public", "hash-kt-ai-outline", timestamp, timestamp, folder["path"],
                folder["id"], "INDEXED", ai_spec["id"], ml_course["id"], "De cuong",
            ),
        )


def test_analyze_file_rejects_oversized_input_before_processing():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        original_limit = main_module.MAX_AI_ANALYZE_BYTES
        main_module.MAX_AI_ANALYZE_BYTES = 4
        try:
            with TestClient(app) as client:
                lecturer = login(client, "GV001")
                response = client.post(
                    "/api/documents/analyze-file",
                    headers={**lecturer, "X-Filename": "large.pdf", "Content-Type": "application/pdf"},
                    content=b"12345",
                )
                assert response.status_code == 413
                assert "AI phân tích trực tiếp" in response.json()["detail"]
        finally:
            main_module.MAX_AI_ANALYZE_BYTES = original_limit


def test_login_and_dashboard_return_role_permissions_for_rbac():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin_login = client.post(
                "/api/auth/login",
                json={"code": "ADMIN", "password": os.environ["EDUVAULT_SEED_PASSWORD_ADMIN"]},
            )
            assert admin_login.status_code == 200
            assert "policy.manage" in admin_login.json()["user"]["permissions"]
            assert "users.manage" in admin_login.json()["user"]["permissions"]

            lecturer = login(client, "GV001")
            dashboard = client.get("/api/dashboard", headers=lecturer)
            assert dashboard.status_code == 200
            permissions = dashboard.json()["user"]["permissions"]
            assert "repository.own" in permissions
            assert "policy.manage" not in permissions


def test_expired_session_is_rejected_and_removed():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            headers = login(client, "GV001")
            token = headers["Authorization"].removeprefix("Bearer ")
            expired_at = (datetime.now(timezone.utc) - timedelta(minutes=999)).isoformat()
            with database.transaction() as db:
                db.execute("UPDATE sessions SET created_at=? WHERE token=?", (expired_at, token))

            response = client.get("/api/dashboard", headers=headers)
            assert response.status_code == 401
            with database.connection() as db:
                assert not db.execute("SELECT 1 FROM sessions WHERE token=?", (token,)).fetchone()


def test_lecturer_assignment_csv_preview_confirm_and_projection():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            lecturer = login(client, "GV001")
            activate_sample_policy(client, admin)

            blocked = client.put("/api/profile/specializations", headers=lecturer, json={"specialization_ids": []})
            assert blocked.status_code == 403

            preview = client.post(
                "/api/lecturer-assignments/import/preview",
                headers={**admin, "X-Filename": "assignments.csv", "Content-Type": "text/csv"},
                content="lecturer_code,lecturer_name,specialization\nGV001,Nguyen Van A,AI\nBAD,Khong Co,AI\n".encode("utf-8"),
            )
            assert preview.status_code == 200
            assert preview.json()["status"] == "has_errors"
            assert preview.json()["summary"] == {"total_rows": 2, "valid_rows": 1, "error_rows": 1, "warning_rows": 0}

            blocked_confirm = client.post(
                "/api/lecturer-assignments/import/confirm",
                headers=admin,
                json={"batch_preview_id": preview.json()["batch_preview_id"]},
            )
            assert blocked_confirm.status_code == 400

            json_preview = client.post(
                "/api/lecturer-assignments/import/preview",
                headers={**admin, "X-Filename": "assignments.json", "Content-Type": "application/json"},
                content=json.dumps([{"lecturer_code": "GVNEW", "lecturer_name": "Le Thu Ha", "specialization": "Data Science"}]).encode("utf-8"),
            )
            assert json_preview.status_code == 200
            assert json_preview.json()["summary"]["valid_rows"] == 1

            confirmed = assign_lecturer_csv(client, admin, [("GV001", "Nguyen Van A", "AI")])
            assert confirmed["status"] == "active"
            assert confirmed["summary"]["provisioned_users"] == 1
            assert confirmed["summary"]["folder_permissions"] > 0

            profile = client.get("/api/profile/specializations", headers=lecturer)
            assert profile.status_code == 200
            assert len(profile.json()["selected_ids"]) == 1

            tree = client.get("/api/my-folder-tree", headers=lecturer)
            assert tree.status_code == 200
            assert [node["name"] for node in tree.json()["children"]] == ["Tri tue nhan tao"]

            assignment = client.get("/api/my-assignment", headers=lecturer)
            assert assignment.status_code == 200
            assert assignment.json()["can_self_select"] is False
            assert assignment.json()["assigned_specializations"][0]["code"] == "AI"

            with database.connection() as db:
                permissions = db.execute("SELECT COUNT(*) count FROM lecturer_folder_permissions WHERE user_code='GV001' AND status='active'").fetchone()["count"]
                assert permissions > 0


def test_policy_activation_preview_reports_tree_and_assignment_impact():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            activate_sample_policy(client, admin)
            assign_lecturer_csv(client, admin, [("GV001", "Nguyen Van A", "AI")])

            next_policy = {
                "faculty": "Khoa CNTT",
                "specializations": [
                    {
                        "name": "Data Science",
                        "code": "DS",
                        "courses": [
                            {"name": "Data Mining", "standard_folders": ["De cuong", "Bai giang", "Lab", "De thi"]},
                        ],
                    },
                    {
                        "name": "Cyber Security",
                        "code": "CS",
                        "courses": [
                            {"name": "Network Security", "standard_folders": ["De cuong", "Bai giang", "Lab", "De thi"]},
                        ],
                    },
                ],
            }
            uploaded = client.post(
                "/api/policies/upload",
                headers={**admin, "X-Filename": "policy-next.json", "X-Title": "Policy Activation Preview", "Content-Type": "application/json"},
                content=json.dumps(next_policy).encode("utf-8"),
            )
            assert uploaded.status_code == 201, uploaded.text

            preview = client.get(f"/api/policies/{uploaded.json()['id']}/activation-preview", headers=admin)
            assert preview.status_code == 200, preview.text
            body = preview.json()
            assert body["tree_impact"]["summary"]["added"] == 1
            assert body["tree_impact"]["summary"]["removed"] == 1
            assert body["assignment_impact"]["valid_assignments"] == 0
            assert body["assignment_impact"]["needs_resolution_assignments"] == 1
            assert body["virtual_tree_impact"]["virtual_trees_to_rebuild"] == 0
            assert body["folder_permission_impact"]["active_permissions_to_deprecate"] > 0

            activated = client.post(f"/api/policies/{uploaded.json()['id']}/activate", headers=admin)
            assert activated.status_code == 200, activated.text
            summary = activated.json()["activation_summary"]
            assert summary["tree_impact"]["summary"]["added"] == 1
            assert summary["assignment_impact"]["needs_resolution_assignments"] == 1


def test_knowledge_transfer_insight_summary():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            seed_knowledge_transfer_insight_data(client, admin)

            response = client.get("/api/knowledge-transfer/insights", headers=admin)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["policy"]["title"] == "Policy Assignment Test"
            assert body["summary"]["course_total_count"] == 3
            assert body["summary"]["document_coverage_percent"] > 0
            assert body["summary"]["critical_gap_count"] > 0


def test_knowledge_transfer_specialization_insight():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            seed_knowledge_transfer_insight_data(client, admin)

            response = client.get("/api/knowledge-transfer/insights/specializations", headers=admin)
            assert response.status_code == 200, response.text
            ai = next(item for item in response.json()["items"] if item["specialization_name"] == "Tri tue nhan tao")
            assert ai["assigned_lecturer_count"] == 1
            assert ai["document_coverage_percent"] > 0
            assert ai["knowledge_risk"] in {"high", "critical"}


def test_knowledge_transfer_course_gap():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            seed_knowledge_transfer_insight_data(client, admin)

            response = client.get("/api/knowledge-transfer/insights/course-gaps", headers=admin)
            assert response.status_code == 200, response.text
            machine_learning = next(item for item in response.json()["items"] if item["course_name"] == "Machine Learning")
            assert machine_learning["coverage_percent"] == 25
            assert set(machine_learning["missing_types"]) == {"Bai giang", "Lab", "De thi"}


def test_knowledge_transfer_lecturer_dependency():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            seed_knowledge_transfer_insight_data(client, admin)

            response = client.get("/api/knowledge-transfer/insights/lecturer-dependency", headers=admin)
            assert response.status_code == 200, response.text
            gv001 = next(item for item in response.json()["items"] if item["lecturer_code"] == "GV001")
            assert gv001["specialization_name"] == "Tri tue nhan tao"
            assert gv001["owned_document_count"] == 1
            assert gv001["dependency_risk"] == "high"


def test_knowledge_transfer_actions_include_course_gap_recommendation():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            seed_knowledge_transfer_insight_data(client, admin)

            response = client.get("/api/knowledge-transfer/actions", headers=admin)
            assert response.status_code == 200, response.text
            machine_learning = next(item for item in response.json() if item["category"] == "course_gap" and "Machine Learning" in item["title"])
            assert machine_learning["priority"] == "critical"
            assert "coverage is 25%" in machine_learning["reason"]


def test_knowledge_transfer_actions_include_lecturer_dependency_recommendation():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            seed_knowledge_transfer_insight_data(client, admin)

            response = client.get("/api/knowledge-transfer/actions", headers=admin)
            assert response.status_code == 200, response.text
            dependency = next(item for item in response.json() if item["category"] == "lecturer_dependency")
            assert dependency["priority"] == "high"
            assert "Chi dinh giang vien du phong" in dependency["recommended_actions"]


def test_knowledge_transfer_actions_include_missing_document_uploads():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            seed_knowledge_transfer_insight_data(client, admin)

            response = client.get("/api/knowledge-transfer/actions", headers=admin)
            assert response.status_code == 200, response.text
            machine_learning = next(item for item in response.json() if item["category"] == "course_gap" and "Machine Learning" in item["title"])
            assert "Upload Lab" in machine_learning["recommended_actions"]
            assert "Upload Bai giang" in machine_learning["recommended_actions"]
            assert "Upload De thi" in machine_learning["recommended_actions"]


def test_legacy_lecturer_specializations_are_migrated_without_loss():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            activate_sample_policy(client, admin)
            with database.transaction() as db:
                spec = db.execute("SELECT id FROM specializations WHERE name='Tri tue nhan tao'").fetchone()
                db.execute(
                    "INSERT OR IGNORE INTO lecturer_specializations(id,user_code,specialization_id,created_at) VALUES(?,?,?,?)",
                    ("legacy-ls-1", "GV001", spec["id"], database.now()),
                )
            database.init_database()
            with database.connection() as db:
                legacy_projection = db.execute("SELECT COUNT(*) count FROM lecturer_specializations WHERE user_code='GV001'").fetchone()["count"]
                legacy_assignment = db.execute("SELECT COUNT(*) count FROM lecturer_assignments WHERE lecturer_code='GV001' AND source='legacy_self_selected'").fetchone()["count"]
            assert legacy_projection == 1
            assert legacy_assignment == 1


def test_upload_accepts_file_larger_than_ai_analysis_limit():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        original_ai_limit = main_module.MAX_AI_ANALYZE_BYTES
        original_upload_limit = main_module.MAX_UPLOAD_BYTES
        main_module.MAX_AI_ANALYZE_BYTES = 4
        main_module.MAX_UPLOAD_BYTES = 64
        try:
            with TestClient(app) as client:
                lecturer = login(client, "GV001")
                response = client.post(
                    "/api/documents/upload",
                    headers={
                        **lecturer,
                        "X-Filename": "large.txt",
                        "X-Title": "Large upload",
                        "X-Topic": "Upload",
                        "X-Doc-Type": "Demo",
                        "X-Visibility": "private",
                        "Content-Type": "text/plain",
                    },
                    content=b"large file content",
                )
                assert response.status_code == 201
                assert response.json()["asset"]["size"] == len(b"large file content")
        finally:
            main_module.MAX_AI_ANALYZE_BYTES = original_ai_limit
            main_module.MAX_UPLOAD_BYTES = original_upload_limit


def test_chunked_upload_reports_progress_and_processes_in_background():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            raw = b"python code programming lesson"
            initialized = client.post(
                "/api/uploads/init",
                headers=lecturer,
                json={
                    "filename": "chunked.txt",
                    "mime_type": "text/plain",
                    "total_bytes": len(raw),
                    "title": "Chunked upload",
                    "topic": "Upload",
                    "doc_type": "Demo",
                    "visibility": "private",
                },
            )
            assert initialized.status_code == 201
            task_id = initialized.json()["id"]

            first = client.post(
                f"/api/uploads/{task_id}/file",
                headers={**lecturer, "X-Upload-Offset": "0", "Content-Type": "application/octet-stream"},
                content=raw[:8],
            )
            assert first.status_code == 200
            assert first.json()["uploaded_bytes"] == 8
            assert first.json()["status"] == "uploading"

            final = client.post(
                f"/api/uploads/{task_id}/file",
                headers={**lecturer, "X-Upload-Offset": "8", "Content-Type": "application/octet-stream"},
                content=raw[8:],
            )
            assert final.status_code == 200
            assert final.json()["uploaded_bytes"] == len(raw)
            assert final.json()["status"] == "uploaded"

            analyzed = client.post(f"/api/uploads/{task_id}/analyze", headers=lecturer)
            assert analyzed.status_code == 202
            status = client.get(f"/api/uploads/{task_id}", headers=lecturer).json()
            assert status["status"] == "pending_confirmation"
            assert not status["document_id"]
            ticket = status["metadata"]["classification_ticket"]
            assert ticket["filename"] == "chunked.txt"
            assert ticket["status"] == "PENDING_CONFIRMATION"

            confirmed = client.post(
                f"/api/uploads/{task_id}/confirm",
                headers=lecturer,
                json={"specialization_id": None, "course_id": None, "document_type": "Tài liệu khác", "visibility": "private"},
            )
            assert confirmed.status_code == 201
            document_id = confirmed.json()["document"]["id"]
            document = client.get(f"/api/documents/{document_id}", headers=lecturer)
            assert document.status_code == 200
            assert document.json()["document_type"] == "Tài liệu khác"

            removed_task = client.delete(f"/api/uploads/{task_id}", headers=lecturer)
            assert removed_task.status_code == 200
            assert removed_task.json()["status"] == "deleted"
            assert client.get(f"/api/documents/{document_id}", headers=lecturer).status_code == 200


def test_pending_upload_can_be_cancelled_before_document_creation():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            raw = b"temporary upload waiting for confirmation"
            initialized = client.post(
                "/api/uploads/init",
                headers=lecturer,
                json={
                    "filename": "cancel-me.txt",
                    "mime_type": "text/plain",
                    "total_bytes": len(raw),
                    "title": "Cancel me",
                    "topic": "Upload",
                    "doc_type": "TÃ i liá»‡u khÃ¡c",
                    "visibility": "private",
                },
            )
            assert initialized.status_code == 201
            task_id = initialized.json()["id"]
            assert client.post(
                f"/api/uploads/{task_id}/file",
                headers={**lecturer, "X-Upload-Offset": "0", "Content-Type": "application/octet-stream"},
                content=raw,
            ).status_code == 200
            analyzed = client.post(f"/api/uploads/{task_id}/analyze", headers=lecturer)
            assert analyzed.status_code == 202
            status = client.get(f"/api/uploads/{task_id}", headers=lecturer).json()
            assert status["status"] == "pending_confirmation"
            assert status["document_id"] is None

            with database.connection() as db:
                before_docs = db.execute("SELECT COUNT(*) count FROM documents").fetchone()["count"]
                task = db.execute("SELECT temp_path FROM upload_tasks WHERE id=?", (task_id,)).fetchone()
                temp_path = Path(task["temp_path"])
                assert temp_path.exists()

            cancelled = client.delete(f"/api/uploads/{task_id}", headers=lecturer)
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"
            assert not temp_path.exists()
            assert client.get(f"/api/uploads/{task_id}", headers=lecturer).status_code == 404
            with database.connection() as db:
                after_docs = db.execute("SELECT COUNT(*) count FROM documents").fetchone()["count"]
                ticket_count = db.execute(
                    "SELECT COUNT(*) count FROM document_classification_tickets WHERE upload_task_id=?",
                    (task_id,),
                ).fetchone()["count"]
            assert after_docs == before_docs
            assert ticket_count == 0


def test_upload_with_long_folder_and_filename_stays_windows_safe():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            long_name = "OceanofPDF.com_AI_Engineering_Building_Applications_Chip_Huyen_" * 3 + ".pdf"
            uploaded = client.post(
                "/api/documents/upload",
                headers={
                    **lecturer,
                    "X-Filename": quote(long_name),
                    "X-Title": "Long path",
                    "X-Topic": quote("Kỹ thuật AI xây dựng ứng dụng với mô hình nền tảng triển khai đánh giá hệ thống AI"),
                    "X-Doc-Type": "sach_hoc_thuat",
                    "X-Visibility": "public",
                    "X-Folder-Path": quote("Công nghệ thông tin/Kỹ thuật AI xây dựng ứng dụng với mô hình nền tảng triển khai đánh giá hệ thống AI/sach_hoc_thuat/public"),
                    "Content-Type": "application/pdf",
                },
                content=b"%PDF-long-path",
            )
            assert uploaded.status_code == 201
            asset_path = Path(uploaded.json()["asset"]["original_path"])
            assert asset_path.exists()
            assert len(str(asset_path)) < 260


def test_mvp_auth_permissions_versioning_and_backup():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            admin = login(client, "ADMIN")

            dashboard = client.get("/api/dashboard", headers=lecturer)
            assert dashboard.status_code == 200
            assert all(doc["id"] != "doc-exam-process" for doc in dashboard.json()["documents"])

            created = client.post(
                "/api/documents",
                headers=lecturer,
                json={
                    "title": "Ghi chú kiểm thử",
                    "doc_type": "Học liệu",
                    "topic": "Kiểm thử",
                    "visibility": "private",
                    "content": "Nội dung riêng của giảng viên.",
                },
            )
            assert created.status_code == 201
            document_id = created.json()["id"]

            detail = client.get(f"/api/documents/{document_id}", headers=lecturer)
            assert detail.status_code == 200
            assert detail.json()["content"]
            assert detail.json()["id"] == document_id

            updated = client.put(
                f"/api/documents/{document_id}",
                headers=lecturer,
                json={
                    "title": "Ghi chú kiểm thử",
                    "doc_type": "Học liệu",
                    "topic": "Kiểm thử",
                    "visibility": "private",
                    "content": "Nội dung phiên bản thứ hai.",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["current_version"] == 2

            versions = client.get(f"/api/documents/{document_id}/versions", headers=lecturer)
            assert [item["version_no"] for item in versions.json()] == [2, 1]

            comparison = client.get(
                f"/api/documents/{document_id}/versions/compare?base_version=1&target_version=2",
                headers=lecturer,
            )
            assert comparison.status_code == 200
            assert comparison.json()["stats"]["added"] == 1
            assert comparison.json()["stats"]["removed"] == 1
            assert comparison.json()["base_content"] == "Nội dung riêng của giảng viên."
            assert comparison.json()["target_content"] == "Nội dung phiên bản thứ hai."

            backup = client.post("/api/admin/backups", headers=admin)
            assert backup.status_code == 201
            assert Path(backup.json()["storage_path"]).exists()
            restored = client.post(f"/api/admin/backups/{backup.json()['id']}/restore", headers=admin)
            assert restored.status_code == 200
            assert restored.json()["status"] == "success"


def test_extended_use_cases():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            newcomer = login(client, "GVNEW")
            head = login(client, "TBM01")
            admin = login(client, "ADMIN")

            assert client.get("/api/onboarding/courses", headers=newcomer).status_code == 200
            assert client.get("/api/onboarding/processes", headers=newcomer).status_code == 200

            transfer = client.post(
                "/api/transfers",
                headers=head,
                json={"course_code": "AI101", "from_code": "GV001", "to_code": "GVNEW", "deadline": "2026-07-01"},
            )
            assert transfer.status_code == 201
            transfer_id = transfer.json()["id"]
            progress = client.put(f"/api/transfers/{transfer_id}/progress", headers=newcomer, json={"progress": 50})
            assert progress.json()["progress"] == 50

            assert client.get("/api/quality", headers=head).status_code == 200
            usage = client.get("/api/reports/usage", headers=head)
            assert usage.status_code == 200
            assert {"action", "actor_code", "created_at"} <= set(usage.json()["action_events"][0])
            compliance = client.get("/api/backups/compliance", headers=head)
            assert compliance.status_code == 200
            assert compliance.json()["copies"] == 3

            permissions = client.get("/api/permissions", headers=lecturer).json()
            restricted_id = permissions["restricted"][0]["id"]
            request = client.post(f"/api/access-requests/{restricted_id}", headers=lecturer)
            assert request.status_code == 201

            policies = client.get("/api/admin/policies", headers=admin)
            assert policies.status_code == 200
            update = client.put("/api/admin/policies/storage_rules", headers=admin, json={"value": {"retention_years": 7}})
            assert update.status_code == 422
            update = client.put(
                "/api/admin/policies/storage_rules",
                headers=admin,
                json={"value": {"naming": "{department}/{topic}/{doc_type}/{visibility}", "retention_years": 7}},
            )
            assert update.status_code == 200

            created_user = client.post(
                "/api/admin/users",
                headers=admin,
                json={"code": "GV002", "name": "Giảng viên thử nghiệm", "role": "lecturer", "department": "CNTT", "password": "secret"},
            )
            assert created_user.status_code == 201


def test_real_file_upload_and_download():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            headers = {
                **lecturer,
                "X-Filename": "ghi_chu_rag.txt",
                "X-Title": "Ghi%20ch%C3%BA%20RAG",
                "X-Topic": "Tr%C3%AD%20tu%E1%BB%87%20nh%C3%A2n%20t%E1%BA%A1o",
                "X-Doc-Type": "H%E1%BB%8Dc%20li%E1%BB%87u",
                "X-Visibility": "public",
                "Content-Type": "text/plain",
            }
            uploaded = client.post("/api/documents/upload", headers=headers, content="Nội dung RAG từ file thật.".encode())
            assert uploaded.status_code == 201
            document_id = uploaded.json()["document"]["id"]
            asset_id = uploaded.json()["asset"]["id"]
            assert uploaded.json()["document"]["folder_path"]
            assert "repository" in uploaded.json()["asset"]["original_path"]

            provenance = client.get(f"/api/documents/{document_id}/provenance", headers=lecturer)
            assert provenance.status_code == 200
            assert provenance.json()["files"][0]["original_name"] == "ghi_chu_rag.txt"

            downloaded = client.get(f"/api/files/{asset_id}", headers=lecturer)
            assert downloaded.status_code == 200
            assert downloaded.content.decode() == "Nội dung RAG từ file thật."

            tree = client.get("/api/folders/tree", headers=lecturer)
            assert tree.status_code == 200

            ai_status = client.get("/api/ai/status", headers=lecturer)
            assert ai_status.json()["provider"] in {"local", "openai"}

            suggestion = client.post(
                "/api/folders/suggest",
                headers=lecturer,
                json={
                    "title": "Bài giảng học máy",
                    "doc_type": "Học liệu",
                    "topic": "Học máy",
                    "visibility": "public",
                    "content": "Nội dung",
                },
            )
            assert suggestion.status_code == 200
            assert "Học máy" in suggestion.json()["folder_path"]


def test_policies_control_behavior_docx_and_rollback():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            admin = login(client, "ADMIN")

            hidden_before = client.get("/api/dashboard", headers=lecturer).json()["documents"]
            assert all(doc["id"] != "doc-exam-process" for doc in hidden_before)

            permission = client.put(
                "/api/admin/policies/permission_rules",
                headers=admin,
                json={"value": {"private_requires_owner_approval": False}},
            )
            assert permission.status_code == 422
            visible_after = client.get("/api/dashboard", headers=lecturer).json()["documents"]
            assert all(doc["id"] != "doc-exam-process" for doc in visible_after)
            request = client.post("/api/access-requests/doc-exam-process", headers=lecturer)
            assert request.status_code == 201

            backup_policy = client.put(
                "/api/admin/policies/backup_321",
                headers=admin,
                json={"value": {"copies": 4, "media": 3, "offsite": 2}},
            )
            assert backup_policy.status_code == 200
            compliance = client.get("/api/backups/compliance", headers=admin).json()
            assert compliance["required"]["copies"] == 4
            assert compliance["compliant"] is False

            buffer = BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    "<w:body><w:p><w:r><w:t>Nội dung DOCX được AI đọc</w:t></w:r></w:p></w:body></w:document>",
                )
            assert "Nội dung DOCX" in services.extract_text("test.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer.getvalue())
            analyzed = client.post(
                "/api/documents/analyze-file",
                headers={**lecturer, "X-Filename": "hoc_may.docx", "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
                content=buffer.getvalue(),
            )
            assert analyzed.status_code == 200
            assert "Nội dung DOCX" in analyzed.json()["content_preview"]
            assert analyzed.json()["folder_path"]

            scanned_pdf = client.post(
                "/api/documents/analyze-file",
                headers={**lecturer, "X-Filename": "de_vatlyhp.pdf", "Content-Type": "application/pdf"},
                content=b"%PDF-invalid-scan-placeholder",
            )
            assert scanned_pdf.status_code == 200
            assert scanned_pdf.json()["folder_path"]
            assert scanned_pdf.json()["metadata"]["title"]

            created = client.post(
                "/api/documents",
                headers=lecturer,
                json={"title": "Rollback test", "doc_type": "Học liệu", "topic": "Test", "visibility": "public", "content": "Phiên bản một"},
            ).json()
            client.put(
                f"/api/documents/{created['id']}",
                headers=lecturer,
                json={"title": "Rollback test", "doc_type": "Học liệu", "topic": "Test", "visibility": "public", "content": "Phiên bản hai"},
            )
            rolled = client.post(f"/api/documents/{created['id']}/rollback/1", headers=lecturer)
            assert rolled.status_code == 200
            assert rolled.json()["current_version"] == 3

            prompt_policy = client.put(
                "/api/admin/policies/ai_prompts",
                headers=admin,
                json={"value": {"metadata_instructions": "Hãy phân loại metadata theo quy định của khoa.", "answer_instructions": "Hãy trả lời ngắn gọn và luôn nêu nguồn tài liệu."}},
            )
            assert prompt_policy.status_code == 200


def test_document_trash_restore_and_permanent_delete():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            owner = login(client, "GV001")
            other = login(client, "GVNEW")
            admin = login(client, "ADMIN")

            created = client.post(
                "/api/documents",
                headers=owner,
                json={"title": "Tài liệu cần xóa", "doc_type": "Học liệu", "topic": "Test", "visibility": "public", "content": "Nội dung chỉ dùng để kiểm thử xóa."},
            )
            document_id = created.json()["id"]

            forbidden = client.delete(f"/api/documents/{document_id}", headers=other)
            assert forbidden.status_code == 403

            deleted = client.delete(f"/api/documents/{document_id}", headers=owner)
            assert deleted.status_code == 200
            assert deleted.json()["status"] == "trashed"
            assert all(doc["id"] != document_id for doc in client.get("/api/dashboard", headers=owner).json()["documents"])
            assert any(doc["id"] == document_id for doc in client.get("/api/trash", headers=owner).json())

            restored = client.post(f"/api/trash/{document_id}/restore", headers=owner)
            assert restored.status_code == 200
            assert any(doc["id"] == document_id for doc in client.get("/api/dashboard", headers=owner).json()["documents"])

            client.delete(f"/api/documents/{document_id}", headers=owner)
            purge_forbidden = client.delete(f"/api/trash/{document_id}", headers=owner)
            assert purge_forbidden.status_code == 403
            purged = client.delete(f"/api/trash/{document_id}", headers=admin)
            assert purged.status_code == 200
            assert purged.json()["status"] == "deleted_permanently"


def test_operations_status_panel_loads():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            status = client.get("/api/operations/status", headers=admin)

    assert status.status_code == 200
    data = status.json()
    assert data["api"]["status"] == "ok"
    assert data["database"]["available"] is True
    assert set(data["storage"]) >= {"storage_used_bytes", "documents_count", "versions_count", "chunks_count"}
    assert set(data["n8n"]) == {"policy_activation", "lecturer_assignment"}
    assert set(data["alerts"]) == {"critical", "warnings", "recent_events"}
    assert isinstance(data["alerts"]["critical"], list)
    assert isinstance(data["alerts"]["warnings"], list)
    assert isinstance(data["alerts"]["recent_events"], list)


def test_operations_heartbeat_update():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            rejected = client.post(
                "/api/operations/n8n/heartbeat",
                json={"workflow": "policy_activation", "status": "success", "detail": {"run": "x"}},
            )
            assert rejected.status_code == 403
            updated = client.post(
                "/api/operations/n8n/heartbeat",
                headers={"X-Internal-Policy-Secret": os.environ["N8N_POLICY_SECRET"]},
                json={"workflow": "policy_activation", "status": "failure", "detail": {"error": "demo"}},
            )

    assert updated.status_code == 200
    assert updated.json()["workflow"] == "policy_activation"
    assert updated.json()["failure_count"] == 1
    assert updated.json()["last_failure_at"]


def test_operations_heartbeat_lifecycle_statuses():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        secret = os.environ["N8N_POLICY_SECRET"]
        healthy_at = datetime.now(timezone.utc).isoformat()
        warning_at = (datetime.now(timezone.utc) - timedelta(minutes=7)).isoformat()
        offline_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        with TestClient(app) as client:
            success = client.post(
                "/api/operations/n8n/heartbeat",
                headers={"X-Internal-Policy-Secret": secret},
                json={
                    "workflow_name": "policy_activation_workflow",
                    "status": "success",
                    "timestamp": healthy_at,
                    "details": "activation completed",
                },
            )
            warning = client.post(
                "/api/operations/n8n/heartbeat",
                headers={"X-Internal-Policy-Secret": secret},
                json={
                    "workflow_name": "lecturer_assignment_workflow",
                    "status": "error",
                    "timestamp": warning_at,
                    "details": {"error": "preview failed"},
                },
            )
            admin = login(client, "ADMIN")
            status = client.get("/api/operations/status", headers=admin)
            client.post(
                "/api/operations/n8n/heartbeat",
                headers={"X-Internal-Policy-Secret": secret},
                json={
                    "workflow_name": "lecturer_assignment_workflow",
                    "status": "success",
                    "timestamp": offline_at,
                    "details": {"run": "old"},
                },
            )
            offline_status = client.get("/api/operations/status", headers=admin)

    assert success.status_code == 200
    assert success.json()["workflow"] == "policy_activation"
    assert success.json()["health"] == "healthy"
    assert warning.status_code == 200
    assert warning.json()["workflow"] == "lecturer_assignment"
    assert warning.json()["last_status"] == "error"
    assert warning.json()["health"] == "warning"
    assert status.json()["n8n"]["policy_activation"]["health"] == "healthy"
    assert status.json()["n8n"]["lecturer_assignment"]["health"] == "warning"
    assert offline_status.json()["n8n"]["lecturer_assignment"]["health"] == "offline"


def test_operations_alert_rules_and_recent_events():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        secret = os.environ["N8N_POLICY_SECRET"]
        stale_backup_at = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        stale_verify_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        offline_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        with database.transaction() as db:
            db.execute(
                "INSERT INTO backup_logs VALUES(?,?,?,?,?)",
                ("backup-stale", str(Path(directory) / "backups" / "backup-stale"), "success", "ADMIN", stale_backup_at),
            )
            db.execute(
                "INSERT INTO ops_restore_verifications VALUES(?,?,?,?,?,?)",
                ("verify-stale", "backup-stale", "verified", json.dumps({"ok": True}), "ADMIN", stale_verify_at),
            )
            services.audit(db, "SYSTEM", "rag.qdrant_fallback", "query", None, {"query": "fallback query"})
        with TestClient(app) as client:
            client.post(
                "/api/operations/n8n/heartbeat",
                headers={"X-Internal-Policy-Secret": secret},
                json={
                    "workflow_name": "policy_activation_workflow",
                    "status": "success",
                    "timestamp": offline_at,
                    "details": "old run",
                },
            )
            admin = login(client, "ADMIN")
            status = client.get("/api/operations/status", headers=admin)

    assert status.status_code == 200
    payload = status.json()
    warning_codes = {item["code"] for item in payload["alerts"]["warnings"]}
    assert "backup_stale" in warning_codes
    assert "restore_verify_stale" in warning_codes
    assert "policy_activation_offline" in warning_codes
    assert any(item["kind"] == "backup" for item in payload["alerts"]["recent_events"])
    assert any(item["kind"] == "restore_verify" for item in payload["alerts"]["recent_events"])
    assert any(item["kind"] == "qdrant_fallback" for item in payload["alerts"]["recent_events"])


def test_restore_verification_dry_run():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            backup = client.post("/api/admin/backups", headers=admin)
            assert backup.status_code == 201
            verified = client.post(f"/api/operations/backups/{backup.json()['id']}/verify", headers=admin)
            status = client.get("/api/operations/status", headers=admin)

    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert verified.json()["detail"]["database_exists"] is True
    assert verified.json()["detail"]["storage_exists"] is True
    assert verified.json()["detail"]["manifest_exists"] is True
    assert verified.json()["detail"]["checksum_valid"] is True
    assert status.json()["last_restore_verification"]["backup_id"] == backup.json()["id"]


def test_backup_writes_manifest_and_checksum():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            backup = client.post("/api/admin/backups", headers=admin)
            assert backup.status_code == 201
            backup_dir = Path(backup.json()["storage_path"])
            manifest = backup_dir / "manifest.json"
            checksum = backup_dir / "checksum.sha256"
            assert manifest.exists()
            assert checksum.exists()
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            assert payload["backup_id"] == backup.json()["id"]
            assert payload["database_snapshot"]["included"] is True
            assert payload["local_storage"]["included"] is True
            assert "documents_count" in payload
            assert "included_components" in payload
            assert "manifest.json" in checksum.read_text(encoding="utf-8")


def test_backup_succeeds_when_qdrant_backup_fails(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        monkeypatch.setattr(services, "_qdrant_backup", lambda _target: {"included": False, "enabled": True, "collections_count": 0, "vectors_count": 0, "error": "qdrant unavailable"})
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            backup = client.post("/api/admin/backups", headers=admin)

    assert backup.status_code == 201
    manifest = backup.json()["manifest"]
    assert manifest["qdrant"]["included"] is False
    assert manifest["qdrant"]["error"] == "qdrant unavailable"
    assert manifest["database_snapshot"]["included"] is True


def test_backup_succeeds_when_minio_backup_fails(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        monkeypatch.setattr(services, "_minio_backup", lambda _target: {"included": False, "enabled": True, "bucket": "eduvault", "objects_count": 0, "size_bytes": 0, "error": "minio unavailable"})
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            backup = client.post("/api/admin/backups", headers=admin)

    assert backup.status_code == 201
    manifest = backup.json()["manifest"]
    assert manifest["minio"]["included"] is False
    assert manifest["minio"]["error"] == "minio unavailable"
    assert manifest["local_storage"]["included"] is True


def test_restore_verification_fails_when_checksum_is_tampered():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            backup = client.post("/api/admin/backups", headers=admin)
            assert backup.status_code == 201
            (Path(backup.json()["storage_path"]) / "manifest.json").write_text("{}", encoding="utf-8")
            verified = client.post(f"/api/operations/backups/{backup.json()['id']}/verify", headers=admin)

    assert verified.status_code == 200
    assert verified.json()["status"] == "failed"
    assert "Checksum" in verified.json()["detail"]["error"]


def test_private_owner_anonymity_and_strict_chatbot_scope():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            requester = login(client, "GV001")
            owner = login(client, "TBM01")
            admin = login(client, "ADMIN")

            restricted = client.get("/api/permissions", headers=requester).json()["restricted"]
            exam = next(item for item in restricted if item["id"] == "doc-exam-process")
            assert exam["owner_code"] == "Ẩn danh"
            assert exam["owner_anonymous"] is True

            access_request = client.post("/api/access-requests/doc-exam-process", headers=requester)
            request_id = access_request.json()["id"]
            assert client.post(f"/api/access-requests/{request_id}/approved", headers=owner).status_code == 200

            requester_dashboard = client.get("/api/dashboard", headers=requester).json()
            approved_private = next(item for item in requester_dashboard["documents"] if item["id"] == "doc-exam-process")
            assert approved_private["owner_code"] == "Ẩn danh"
            requester_request = next(item for item in requester_dashboard["requests"] if item["id"] == request_id)
            assert requester_request["owner_code"] == "Ẩn danh"

            versions = client.get("/api/documents/doc-exam-process/versions", headers=requester).json()
            assert all(item["created_by"] == "Ẩn danh" for item in versions)

            requester_answer = client.post("/api/search", headers=requester, json={"question": "phản biện chéo đề thi"}).json()
            assert requester_answer["scope"] == "public_or_owned"
            assert all(item["id"] != "doc-exam-process" for item in requester_answer["citations"])

            admin_answer = client.post("/api/search", headers=admin, json={"question": "phản biện chéo đề thi"}).json()
            assert all(item["id"] != "doc-exam-process" for item in admin_answer["citations"])

            owner_answer = client.post("/api/search", headers=owner, json={"question": "phản biện chéo đề thi"}).json()
            assert any(item["id"] == "doc-exam-process" for item in owner_answer["citations"])
            assert all(section in owner_answer["answer"] for section in (
                "### Nội dung trọng tâm",
                "### Những phần cần chú ý",
                "### Gợi ý học tập",
                "### Bạn có thể hỏi tiếp",
            ))
            assert not owner_answer["answer"].startswith(("Nguồn tài liệu", "Tóm tắt", "Kết quả"))

            pipeline = client.get("/api/rag/pipeline", headers=requester)
            assert pipeline.status_code == 200
            assert pipeline.json()["scope"] == "public_or_owned"
            assert [stage["name"] for stage in pipeline.json()["stages"]] == [
                "upload", "parse_pdf_docx_ocr", "chunk", "embedding", "vector_store", "permission_filter", "retrieve_answer"
            ]


def test_chatbot_stream_emits_status_deltas_and_citations():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            response = client.post(
                "/api/search/stream",
                headers=lecturer,
                json={"question": "Tài liệu học máy nói về nội dung gì?"},
            )

            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/x-ndjson")
            events = [json.loads(line) for line in response.text.splitlines()]
            assert events[0]["type"] == "status"
            assert any(event["type"] == "delta" and event["text"] for event in events)
            assert events[-1]["type"] == "complete"
            assert "citations" in events[-1]
            assert "trace_id" in events[-1]
            assert "verification" in events[-1]


def test_prd_search_trace_filters_and_feedback_are_persisted():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")

            response = client.post(
                "/api/search",
                headers=lecturer,
                json={
                    "question": "tai lieu RAG pipeline noi ve gi",
                    "filters": {"doc_type": "Học liệu"},
                },
            )

            assert response.status_code == 200
            result = response.json()
            assert result["intent"] in {"document_lookup", "topic_search", "question_answer"}
            assert "tài liệu" in result["rewritten_query"]
            assert result["trace_id"].startswith("trace-")
            assert result["verification"]["status"] in {"grounded", "weak_evidence"}
            assert result["trace"]["filters"]["doc_type"] == "Học liệu"
            assert result["trace"]["retrieved"]
            assert result["citations"]
            assert all("chunk" in item and item["chunk"] for item in result["citations"])
            assert all(item["id"] != "doc-de-cuong-ai" for item in result["citations"])

            feedback = client.post(
                "/api/search/feedback",
                headers=lecturer,
                json={"trace_id": result["trace_id"], "rating": "wrong_source", "reason": "Sai nguồn", "detail": "Nguồn chưa phù hợp."},
            )
            assert feedback.status_code == 201

            admin = login(client, "ADMIN")
            usage = client.get("/api/reports/usage", headers=admin).json()
            assert any(item["query"] == result["rewritten_query"] for item in usage["popular_queries"])
            assert any(item["rating"] == "wrong_source" for item in usage["bad_feedback"])


def test_chatbot_book_request_does_not_cite_exam_documents():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            exam = client.post(
                "/api/documents",
                headers=lecturer,
                json={
                    "title": "Đề thi AI cuối kỳ",
                    "doc_type": "Đề thi",
                    "topic": "Trí tuệ nhân tạo",
                    "visibility": "public",
                    "content": "Đề thi môn AI có câu hỏi về machine learning và trí tuệ nhân tạo.",
                },
            )
            assert exam.status_code == 201

            answer = client.post(
                "/api/search",
                headers=lecturer,
                json={"question": "Tôi cần sách AI bạn hãy gợi ý cho tôi"},
            )

            assert answer.status_code == 200
            result = answer.json()
            assert all(item["id"] != exam.json()["id"] for item in result["citations"])
            assert "sách AI" in result["answer"]
            assert "chưa tìm thấy" in result["answer"].lower()


def test_private_file_requires_owner_approval_before_download():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            owner = login(client, "GV001")
            requester = login(client, "GVNEW")
            head = login(client, "TBM01")
            admin = login(client, "ADMIN")
            uploaded = client.post(
                "/api/documents/upload",
                headers={
                    **owner,
                    "X-Filename": "private.txt",
                    "X-Title": "Private",
                    "X-Topic": "Test",
                    "X-Doc-Type": "Hoc lieu",
                    "X-Visibility": "private",
                    "Content-Type": "text/plain",
                },
                content=b"private-content",
            )
            document_id = uploaded.json()["document"]["id"]
            asset_id = uploaded.json()["asset"]["id"]

            for unauthorized in (requester, head, admin):
                assert client.get(f"/api/documents/{document_id}", headers=unauthorized).status_code == 403
                assert client.get(f"/api/documents/{document_id}/versions", headers=unauthorized).status_code == 403
                assert client.get(f"/api/documents/{document_id}/provenance", headers=unauthorized).status_code == 403
                assert client.get(f"/api/files/{asset_id}", headers=unauthorized).status_code == 403
                assert client.delete(f"/api/documents/{document_id}", headers=unauthorized).status_code == 403

            admin_update = client.put(
                f"/api/documents/{document_id}",
                headers=admin,
                json={"title": "Private", "doc_type": "Hoc lieu", "topic": "Test", "visibility": "private", "content": "changed"},
            )
            assert admin_update.status_code == 403
            assert client.post(f"/api/documents/{document_id}/rollback/1", headers=admin).status_code == 403

            access_request = client.post(f"/api/access-requests/{document_id}", headers=requester)
            assert access_request.status_code == 201
            request_id = access_request.json()["id"]
            assert client.post(f"/api/access-requests/{request_id}/approved", headers=admin).status_code == 403
            assert client.get(f"/api/files/{asset_id}", headers=requester).status_code == 403

            assert client.post(f"/api/access-requests/{request_id}/approved", headers=owner).status_code == 200
            assert client.get(f"/api/documents/{document_id}", headers=requester).status_code == 200
            assert client.get(f"/api/files/{asset_id}", headers=requester).content == b"private-content"
            provenance = client.get(f"/api/documents/{document_id}/provenance", headers=requester).json()
            assert provenance["access"] == {"type": "approved_request", "request_id": request_id}
            assert client.post(f"/api/access-requests/{request_id}/revoke", headers=admin).status_code == 403
            assert client.post(f"/api/access-requests/{request_id}/revoke", headers=owner).status_code == 200
            assert client.get(f"/api/files/{asset_id}", headers=requester).status_code == 403


def test_personal_cloud_connections_are_scoped_per_user():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            other = login(client, "GVNEW")

            connections = client.get("/api/cloud/connections", headers=lecturer)
            assert connections.status_code == 200
            assert {item["provider"] for item in connections.json()} == {"google_drive", "onedrive"}
            assert all(item["connected"] is False for item in connections.json())

            with database.transaction() as db:
                db.execute(
                    """INSERT INTO cloud_connections(user_code,provider,account_email,access_token,refresh_token,expires_in,status,created_at,updated_at)
                       VALUES('GV001','google_drive','gv001@example.edu','','',0,'connected',?,?)""",
                    (database.now(), database.now()),
                )
            owner_connections = client.get("/api/cloud/connections", headers=lecturer).json()
            other_connections = client.get("/api/cloud/connections", headers=other).json()
            assert next(item for item in owner_connections if item["provider"] == "google_drive")["connected"] is True
            assert next(item for item in other_connections if item["provider"] == "google_drive")["connected"] is False

            disconnected = client.delete("/api/cloud/connections/google_drive", headers=lecturer)
            assert disconnected.status_code == 200


def test_manual_cloud_sync_uses_original_file_for_current_version():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            uploaded = client.post(
                "/api/documents/upload",
                headers={
                    **lecturer,
                    "X-Filename": "syllabus.pdf",
                    "X-Title": "Cloud sync PDF",
                    "X-Topic": "Cloud",
                    "X-Doc-Type": "Syllabus",
                    "X-Visibility": "private",
                    "Content-Type": "application/pdf",
                },
                content=b"%PDF-1.4 original-pdf",
            )
            assert uploaded.status_code == 201
            document_id = uploaded.json()["document"]["id"]

            with database.transaction() as db:
                db.execute(
                    """INSERT INTO cloud_connections(user_code,provider,account_email,access_token,refresh_token,expires_in,status,created_at,updated_at)
                       VALUES('GV001','google_drive','gv001@example.edu','','',0,'connected',?,?)""",
                    (database.now(), database.now()),
                )

            synced_sources = []

            def capture_sync(db, user_code, synced_document_id, source, provider=None):
                synced_sources.append((synced_document_id, source, provider))
                return [{"provider": provider, "status": "success", "remote": "google-drive:test"}]

            with patch.object(main_module, "sync_user_document", side_effect=capture_sync):
                response = client.post("/api/cloud/connections/google_drive/sync", headers=lecturer)

            assert response.status_code == 200
            source = next(source for item_id, source, _ in synced_sources if item_id == document_id)
            assert source.suffix == ".pdf"
            assert source.read_bytes() == b"%PDF-1.4 original-pdf"


def test_v2_object_refs_outbox_and_exam_publication_policy():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            head = login(client, "TBM01")
            admin = login(client, "ADMIN")

            created = client.post(
                "/api/documents",
                headers=lecturer,
                json={
                    "title": "Đề thi cuối kỳ AI",
                    "doc_type": "Đề thi",
                    "topic": "Khảo thí",
                    "visibility": "private",
                    "content": "Nội dung đề thi V2 cần được bảo mật trước ngày thi.",
                },
            )
            assert created.status_code == 201
            document_id = created.json()["id"]

            status = client.get("/api/v2/status", headers=admin)
            assert status.status_code == 200
            assert status.json()["architecture"] == "v2-hybrid"
            assert status.json()["capacity_target_gb"] == 100
            assert status.json()["objects"]
            assert status.json()["outbox"]

            assert client.get(f"/api/documents/{document_id}", headers=head).status_code == 403
            assert client.get(f"/api/documents/{document_id}", headers=admin).status_code == 403

            schedule = client.post(
                f"/api/v2/exams/{document_id}/schedule-publication",
                headers=head,
                json={"publish_after": "2020-01-01T00:00:00+00:00"},
            )
            assert schedule.status_code == 200
            assert schedule.json()["classification"] == "confidential"

            published = client.post("/api/v2/exams/process-publications", headers=head)
            assert published.status_code == 200
            assert document_id in published.json()["documents"]
            assert client.get(f"/api/documents/{document_id}", headers=admin).status_code == 200


def test_policy_master_tree_specialization_virtual_view_and_upload_guard():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            lecturer = login(client, "GV001")

            policy_payload = {
                "faculty": "Khoa CNTT",
                "specializations": [
                    {
                        "name": "Tri tue nhan tao",
                        "courses": [
                            {"name": "AI Application", "standard_folders": ["De cuong", "Bai giang", "Lab", "De thi", "Tai lieu tham khao"]},
                            {"name": "Machine Learning", "standard_folders": ["De cuong", "Bai giang", "Lab", "De thi"]},
                            {"name": "Natural Language Processing", "standard_folders": ["Bai giang", "Slide", "Tai lieu tham khao", "Video bai giang"]},
                        ],
                    },
                    {
                        "name": "Data Science",
                        "courses": [{"name": "Data Mining", "standard_folders": ["De cuong", "Lab", "De thi"]}],
                    },
                ],
            }
            uploaded = client.post(
                "/api/policies/upload",
                headers={**admin, "X-Filename": "policy.json", "X-Title": "Policy hoc lieu CNTT", "Content-Type": "application/json"},
                content=json.dumps(policy_payload).encode(),
            )
            assert uploaded.status_code == 201
            assert uploaded.json()["status"] == "draft"
            draft_to_delete = client.post(
                "/api/policies/upload",
                headers={**admin, "X-Filename": "delete-policy.json", "X-Title": "Policy xoa thu", "Content-Type": "application/json"},
                content=json.dumps(policy_payload).encode(),
            )
            assert draft_to_delete.status_code == 201
            deleted_draft = client.delete(f"/api/policies/{draft_to_delete.json()['id']}", headers=admin)
            assert deleted_draft.status_code == 200
            assert deleted_draft.json()["status"] == "deleted"

            activated = client.post(f"/api/policies/{uploaded.json()['id']}/activate", headers=admin)
            assert activated.status_code == 200
            assert activated.json()["status"] == "active"
            delete_active = client.delete(f"/api/policies/{uploaded.json()['id']}", headers=admin)
            assert delete_active.status_code == 400

            master = client.get("/api/admin/master-tree", headers=admin)
            assert master.status_code == 200
            spec_names = [node["name"] for node in master.json()["tree"]["children"]]
            assert master.json()["tree"]["name"] == "Khoa CNTT"
            assert spec_names == ["Data Science", "Tri tue nhan tao"]
            ai_master = next(node for node in master.json()["tree"]["children"] if node["name"] == "Tri tue nhan tao")
            assert [node["type"] for node in ai_master["children"]] == ["course", "course", "course"]
            assert next(node for node in ai_master["children"] if node["name"] == "AI Application")["children"][0]["type"] == "standard_folder"

            master_alias = client.get("/master-tree", headers=admin)
            assert master_alias.status_code == 200
            assert master_alias.json()[0]["name"] == "Khoa CNTT"
            api_master_alias = client.get("/api/master-folder-tree", headers=admin)
            assert api_master_alias.status_code == 200
            assert api_master_alias.json()[0]["children"][0]["type"] == "specialization"

            specializations = client.get("/api/specializations", headers=lecturer)
            assert specializations.status_code == 200
            ai_summary = next(item for item in specializations.json() if item["name"] == "Tri tue nhan tao")
            assert ai_summary["courses_count"] == 3

            profile = client.get("/api/profile/specializations", headers=lecturer)
            assert profile.status_code == 200
            ai_spec = next(item for item in profile.json()["available"] if item["name"] == "Tri tue nhan tao")
            ds_spec = next(item for item in profile.json()["available"] if item["name"] == "Data Science")

            empty_tree = client.get("/api/my-folder-tree", headers=lecturer).json()
            assert empty_tree["children"] == []
            assert "chua chon" in empty_tree["message"]

            selected = client.put("/api/profile/specializations", headers=lecturer, json={"specialization_ids": [ai_spec["id"]]})
            assert selected.status_code == 403
            assigned = assign_lecturer_csv(client, admin, [("GV001", "Nguyen Van A", "Tri tue nhan tao")])
            assert assigned["summary"]["provisioned_users"] == 1
            profile_after_assignment = client.get("/api/profile/specializations", headers=lecturer)
            assert profile_after_assignment.status_code == 200
            assert profile_after_assignment.json()["selected_ids"] == [ai_spec["id"]]

            my_tree = client.get("/api/my-folder-tree", headers=lecturer).json()
            assert [node["name"] for node in my_tree["children"]] == ["Tri tue nhan tao"]
            ai_course = next(child for child in my_tree["children"][0]["children"] if child["name"] == "AI Application")
            nlp_course = next(child for child in my_tree["children"][0]["children"] if child["name"] == "Natural Language Processing")
            nlp_reference = next(child for child in nlp_course["children"] if child["name"] == "Tai lieu tham khao")
            ai_reference = next(child for child in ai_course["children"] if child["name"] == "Tai lieu tham khao")
            ai_lab = next(child for child in ai_course["children"] if child["name"] == "Lab")
            ai_exam = next(child for child in ai_course["children"] if child["name"] == "De thi")

            virtual_alias = client.get("/virtual-tree/GV001", headers=lecturer)
            assert virtual_alias.status_code == 200
            assert virtual_alias.json()[0]["name"] == "Tri tue nhan tao"

            lecturer_tree = client.get("/api/lecturers/GV001/folder-tree", headers=lecturer)
            assert lecturer_tree.status_code == 200
            assert lecturer_tree.json()[0]["name"] == "Kho của tôi"
            assert lecturer_tree.json()[0]["children"][0]["name"] == "Tri tue nhan tao"

            repeat_selection = client.post(
                "/api/lecturers/GV001/specializations",
                headers=lecturer,
                json={"specialization_ids": [ai_spec["id"]]},
            )
            assert repeat_selection.status_code == 403
            repeat_selection = client.post(
                "/api/lecturers/GV001/specializations",
                headers=admin,
                json={"specialization_ids": [ai_spec["id"]]},
            )
            assert repeat_selection.status_code == 200
            with database.connection() as db:
                active_clones = db.execute(
                    "SELECT COUNT(*) count FROM lecturer_folder_nodes WHERE user_code='GV001' AND status='active'"
                ).fetchone()["count"]
            repeat_tree = client.get("/api/lecturers/GV001/folder-tree", headers=lecturer).json()
            assert active_clones == 1 + 3 + 13
            assert repeat_tree[0]["children"][0]["children"][0]["children"][0]["type"] == "folder"

            forbidden = client.post(
                "/api/documents/upload",
                headers={
                    **lecturer,
                    "X-Filename": "ml.txt",
                    "X-Title": "ML forbidden",
                    "X-Topic": "Data Mining",
                    "X-Doc-Type": "Lab",
                    "X-Visibility": "public",
                    "X-Folder-Node-Id": ds_spec["folder_node_id"],
                    "Content-Type": "text/plain",
                },
                content=b"cannot upload here",
            )
            assert forbidden.status_code == 403

            allowed = client.post(
                "/api/documents/upload",
                headers={
                    **lecturer,
                    "X-Filename": "ai_lab.txt",
                    "X-Title": "AI lab allowed",
                    "X-Topic": "AI Application",
                    "X-Doc-Type": "Lab",
                    "X-Visibility": "public",
                    "X-Folder-Node-Id": ai_lab["id"],
                    "Content-Type": "text/plain",
                },
                content=b"allowed ai lab upload",
            )
            assert allowed.status_code == 201
            assert allowed.json()["document"]["folder_node_id"] == ai_lab["id"]

            course_level_upload = client.post(
                "/api/documents/upload",
                headers={
                    **lecturer,
                    "X-Filename": "ai_reference.txt",
                    "X-Title": "AI reference book",
                    "X-Topic": "AI Application",
                    "X-Doc-Type": "Slide",
                    "X-Visibility": "public",
                    "X-Folder-Node-Id": ai_course["id"],
                    "Content-Type": "text/plain",
                },
                content=b"reference book for ai application",
            )
            assert course_level_upload.status_code == 409
            assert course_level_upload.json()["detail"] == "Document must be saved inside a document-type folder."

            with database.connection() as db:
                db.execute(
                    "UPDATE documents SET folder_node_id=?,folder_path=?,doc_type=?,document_type=? WHERE id=?",
                    (ai_course["id"], ai_course["path"], "Lab", "Lab", allowed.json()["document"]["id"]),
                )
                database.migrate_document_type_folder_placement(db)
                migrated = db.execute(
                    "SELECT d.folder_node_id,n.type,n.parent_id,n.name FROM documents d JOIN folder_nodes n ON n.id=d.folder_node_id WHERE d.id=?",
                    (allowed.json()["document"]["id"],),
                ).fetchone()
            assert migrated["type"] == "standard_folder"
            assert migrated["parent_id"] == ai_course["id"]
            assert migrated["name"] == "Lab"

            book_raw = b"Build a Large Language Model From Scratch reference material"
            book_init = client.post(
                "/api/uploads/init",
                headers=lecturer,
                json={
                    "filename": "Build a Large Language Model From Scratch.pdf",
                    "mime_type": "application/pdf",
                    "total_bytes": len(book_raw),
                    "title": "Build a Large Language Model From Scratch",
                    "topic": "Natural Language Processing",
                    "doc_type": "Tài liệu khác",
                    "visibility": "public",
                },
            )
            assert book_init.status_code == 201
            book_task_id = book_init.json()["id"]
            assert client.post(
                f"/api/uploads/{book_task_id}/file",
                headers={**lecturer, "X-Upload-Offset": "0", "Content-Type": "application/octet-stream"},
                content=book_raw,
            ).status_code == 200
            assert client.post(f"/api/uploads/{book_task_id}/analyze", headers=lecturer).status_code == 202
            confirmed_book = client.post(
                f"/api/uploads/{book_task_id}/confirm",
                headers=lecturer,
                json={
                    "specialization_id": ai_spec["id"],
                    "course_id": nlp_course["id"],
                    "document_type": "Tài liệu khác",
                    "visibility": "public",
                    "final_destination_source": "manual",
                },
            )
            assert confirmed_book.status_code == 201
            book_document = confirmed_book.json()["document"]
            assert book_document["folder_node_id"] == nlp_reference["id"]
            assert book_document["folder_node_id"] != nlp_course["id"]
            assert book_document["course_id"] == nlp_course["id"]

            raw = b"Machine Learning final review and model evaluation"
            initialized = client.post(
                "/api/uploads/init",
                headers=lecturer,
                json={
                    "filename": "machine-learning-review.txt",
                    "mime_type": "text/plain",
                    "total_bytes": len(raw),
                    "title": "Manual destination wins",
                    "topic": "Machine Learning",
                    "doc_type": "Slide",
                    "visibility": "public",
                },
            )
            assert initialized.status_code == 201
            task_id = initialized.json()["id"]
            uploaded_file = client.post(
                f"/api/uploads/{task_id}/file",
                headers={**lecturer, "X-Upload-Offset": "0", "Content-Type": "application/octet-stream"},
                content=raw,
            )
            assert uploaded_file.status_code == 200
            analyzed = client.post(f"/api/uploads/{task_id}/analyze", headers=lecturer)
            assert analyzed.status_code == 202
            ticket = client.get(f"/api/uploads/{task_id}", headers=lecturer).json()["metadata"]["classification_ticket"]
            assert ticket["suggested_course"] == "Machine Learning"
            confirmed_manual = client.post(
                f"/api/uploads/{task_id}/confirm",
                headers=lecturer,
                json={
                    "specialization_id": ticket["suggested_specialization_id"],
                    "course_id": ticket["suggested_course_id"],
                    "folder_node_id": ai_exam["id"],
                    "document_type": "Slide",
                    "visibility": "public",
                },
            )
            assert confirmed_manual.status_code == 201
            manual_document = confirmed_manual.json()["document"]
            assert manual_document["folder_node_id"] == ai_exam["id"]
            assert manual_document["course_id"] == ai_course["id"]
            assert manual_document["document_type"] == "De thi"

            raw_reference = b"Manual reference destination should ignore AI suggestions"
            reference_init = client.post(
                "/api/uploads/init",
                headers=lecturer,
                json={
                    "filename": "manual-reference.txt",
                    "mime_type": "text/plain",
                    "total_bytes": len(raw_reference),
                    "title": "Manual reference destination",
                    "topic": "AI Application",
                    "doc_type": "SÃ¡ch tham kháº£o",
                    "visibility": "public",
                },
            )
            assert reference_init.status_code == 201
            reference_task_id = reference_init.json()["id"]
            assert client.post(
                f"/api/uploads/{reference_task_id}/file",
                headers={**lecturer, "X-Upload-Offset": "0", "Content-Type": "application/octet-stream"},
                content=raw_reference,
            ).status_code == 200
            assert client.post(f"/api/uploads/{reference_task_id}/analyze", headers=lecturer).status_code == 202
            confirmed_reference = client.post(
                f"/api/uploads/{reference_task_id}/confirm",
                headers=lecturer,
                json={
                    "specialization_id": ai_spec["id"],
                    "course_id": ai_course["id"],
                    "folder_node_id": ai_reference["id"],
                    "document_type": "SÃ¡ch tham kháº£o",
                    "visibility": "public",
                    "final_destination_source": "manual",
                },
            )
            assert confirmed_reference.status_code == 201
            reference_document = confirmed_reference.json()["document"]
            assert reference_document["folder_node_id"] == ai_reference["id"]
            assert reference_document["course_id"] == ai_course["id"]
            assert reference_document["document_type"] == ai_reference["name"]

            both = assign_lecturer_csv(client, admin, [
                ("GV001", "Nguyen Van A", "Tri tue nhan tao"),
                ("GV001", "Nguyen Van A", "Data Science"),
            ])
            assert both["summary"]["provisioned_users"] == 1
            expanded_tree = client.get("/api/my-folder-tree", headers=lecturer).json()
            assert [node["name"] for node in expanded_tree["children"]] == ["Data Science", "Tri tue nhan tao"]

            removed = assign_lecturer_csv(client, admin, [("GV001", "Nguyen Van A", "Data Science")])
            assert removed["summary"]["provisioned_users"] == 1
            reduced_tree = client.get("/api/my-folder-tree", headers=lecturer).json()
            assert [node["name"] for node in reduced_tree["children"]] == ["Data Science"]


def test_policy_parser_v2_uses_only_specialization_section_for_master_tree():
    policy_text = """
Phiên bản: 1.0
Ngày hiệu lực: 01/01/2026

1. Mục đích
Hệ thống EduVault phải sử dụng chính sách này để quản lý học liệu.

2. Nhóm chuyên môn
2.1 Trí tuệ nhân tạo (Artificial Intelligence)
Mã: AI
Học phần:
- Machine Learning
- Deep Learning
- Computer Vision

2.2 Khoa học dữ liệu (Data Science)
Mã: DS
Học phần:
- Data Mining
- Big Data Analytics

3. Cấu trúc thư mục chuẩn
- Đề cương môn học
- Bài giảng
- Slide
- Lab

4. Chính sách tạo cây giảng viên
Giảng viên chỉ thấy nhóm chuyên môn đã chọn.

5. Chính sách phân quyền
Public:
- Đề cương
- Bài giảng
Restricted:
- Đề thi
- Đáp án
Confidential:
- Hồ sơ kiểm định

6. Chính sách đồng bộ
Đồng bộ theo lịch.

7. Chính sách lưu trữ
- Versioning bắt buộc.
- Hỗ trợ rollback.
- Lưu thùng rác 30 ngày.
- Backup theo quy tắc 3-2-1.
"""
    parsed = services.parse_policy_tree(policy_text)

    assert set(parsed) >= {
        "master_tree_json",
        "folder_template_json",
        "permission_rules_json",
        "storage_rules_json",
    }
    master_tree = parsed["master_tree_json"]
    spec_names = [item["name_vi"] for item in master_tree["specializations"]]
    assert spec_names == ["Trí tuệ nhân tạo", "Khoa học dữ liệu"]
    assert master_tree["specializations"][0]["name_en"] == "Artificial Intelligence"
    assert master_tree["specializations"][0]["code"] == "AI"
    assert [course["name"] for course in master_tree["specializations"][0]["courses"]] == [
        "Machine Learning",
        "Deep Learning",
        "Computer Vision",
    ]

    encoded_master = json.dumps(master_tree, ensure_ascii=False)
    for invalid_name in ["Phiên bản", "Ngày hiệu lực", "Public", "Restricted", "Confidential", "Hệ thống EduVault phải sử dụng chính sách này để"]:
        assert invalid_name not in encoded_master

    assert parsed["folder_template_json"]["standard_folders"] == ["Đề cương môn học", "Bài giảng", "Slide", "Lab"]
    assert parsed["permission_rules_json"] == {
        "public": ["Đề cương", "Bài giảng"],
        "restricted": ["Đề thi", "Đáp án"],
        "confidential": ["Hồ sơ kiểm định"],
    }
    assert parsed["storage_rules_json"]["rules"] == [
        "Versioning bắt buộc.",
        "Hỗ trợ rollback.",
        "Lưu thùng rác 30 ngày.",
        "Backup theo quy tắc 3-2-1.",
    ]


def test_policy_assistant_preview_confirm_internal_apply_and_rollback():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            head = login(client, "TBM01")
            lecturer = login(client, "GV001")

            policy_payload = {
                "faculty": "CNTT",
                "specializations": [
                    {"name": "AI", "courses": [{"name": "Machine Learning", "standard_folders": ["Bai giang", "De thi"]}]},
                    {"name": "Data Science", "courses": [{"name": "Data Mining", "standard_folders": ["Lab"]}]},
                ],
            }
            uploaded = client.post(
                "/api/policies/upload",
                headers={**admin, "X-Filename": "policy.json", "X-Title": "Policy assistant seed", "Content-Type": "application/json"},
                content=json.dumps(policy_payload).encode(),
            )
            assert uploaded.status_code == 201
            assert client.post(f"/api/policies/{uploaded.json()['id']}/activate", headers=admin).status_code == 200

            forbidden = client.post("/api/policy-assistant/preview", headers=lecturer, json={"message": "Them AI Agent thuoc AI"})
            assert forbidden.status_code == 403

            preview = client.post("/api/policy-assistant/preview", headers=head, json={"message": "Them AI Agent thuoc AI"})
            assert preview.status_code == 200
            assert preview.json()["status"] == "preview"
            assert preview.json()["action"]["action"] == "add_node"

            before_tree = client.get("/api/admin/master-tree", headers=head).json()["tree"]
            assert all(child["name"] != "AI Agent" for child in next(node for node in before_tree["children"] if node["name"] == "AI")["children"])

            confirmed = client.post(
                "/api/policy-assistant/confirm",
                headers=head,
                json={"message": "Them AI Agent thuoc AI", "action": preview.json()["action"], "preview": preview.json()["preview"]},
            )
            assert confirmed.status_code == 200
            assert confirmed.json()["n8n"]["status"] == "not_configured"
            request_id = confirmed.json()["id"]

            after_confirm_tree = client.get("/api/admin/master-tree", headers=head).json()["tree"]
            assert all(child["name"] != "AI Agent" for child in next(node for node in after_confirm_tree["children"] if node["name"] == "AI")["children"])

            rejected_internal = client.post(
                "/internal/policy/apply",
                json={"request_id": request_id, "actor": "TBM01", "action": preview.json()["action"]},
            )
            assert rejected_internal.status_code == 403

            applied = client.post(
                "/internal/policy/apply",
                headers={"X-Internal-Policy-Secret": os.environ["N8N_POLICY_SECRET"]},
                json={"request_id": request_id, "actor": "TBM01", "action": preview.json()["action"]},
            )
            assert applied.status_code == 200
            audit_id = applied.json()["audit_log_id"]
            master = client.get("/api/admin/master-tree", headers=head).json()["tree"]
            ai = next(node for node in master["children"] if node["name"] == "AI")
            assert "AI Agent" in [child["name"] for child in ai["children"]]

            audits = client.get("/api/policy-assistant/audit", headers=head)
            assert audits.status_code == 200
            assert audits.json()[0]["id"] == audit_id

            rolled_back = client.post(
                "/internal/policy/rollback",
                headers={"X-Internal-Policy-Secret": os.environ["N8N_POLICY_SECRET"]},
                json={"audit_log_id": audit_id, "actor": "TBM01"},
            )
            assert rolled_back.status_code == 200
            restored = client.get("/api/admin/master-tree", headers=head).json()["tree"]
            restored_ai = next(node for node in restored["children"] if node["name"] == "AI")
            assert "AI Agent" not in [child["name"] for child in restored_ai["children"]]

            course_preview = client.post(
                "/api/policy-assistant/preview",
                headers=head,
                json={"message": "Thêm học phần Data Engineering vào Data Science"},
            )
            assert course_preview.status_code == 200
            assert course_preview.json()["action"]["action"] == "add_node"
            assert course_preview.json()["action"]["node"] == "Data Engineering"

            course_confirmed = client.post(
                "/api/policy-assistant/confirm",
                headers=head,
                json={
                    "message": "Thêm học phần Data Engineering vào Data Science",
                    "action": course_preview.json()["action"],
                    "preview": course_preview.json()["preview"],
                    "apply_now": True,
                },
            )
            assert course_confirmed.status_code == 200
            assert course_confirmed.json()["applied"]["status"] == "applied"
            master = client.get("/api/admin/master-tree", headers=head).json()["tree"]
            data_science = next(node for node in master["children"] if node["name"] == "Data Science")
            assert "Data Engineering" in [child["name"] for child in data_science["children"]]

            permission_preview = client.post(
                "/api/policy-assistant/preview",
                headers=head,
                json={"message": "Đề thi chỉ trưởng bộ môn được xem"},
            )
            assert permission_preview.status_code == 200
            assert permission_preview.json()["action"]["action"] == "update_permission"

            permission_confirmed = client.post(
                "/api/policy-assistant/confirm",
                headers=head,
                json={
                    "message": "Đề thi chỉ trưởng bộ môn được xem",
                    "action": permission_preview.json()["action"],
                    "preview": permission_preview.json()["preview"],
                    "apply_now": True,
                },
            )
            assert permission_confirmed.status_code == 200
            assert permission_confirmed.json()["applied"]["status"] == "applied"


def test_knowledge_governance_assignment_agent_phase1():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            with database.transaction() as db:
                db.execute(
                    "INSERT INTO users(code,name,role,department,password_hash,active) VALUES(?,?,?,?,?,1)",
                    ("GV002", "Giang Vien Hai", "lecturer", "CNTT", database.hash_secret("GV002")),
                )
            policy_payload = {
                "faculty": "CNTT",
                "specializations": [
                    {"name": "AI", "code": "AI", "courses": [{"name": "Machine Learning", "standard_folders": ["De cuong", "Lab"]}]},
                    {"name": "Data Science", "code": "DS", "courses": [{"name": "Data Mining", "standard_folders": ["De cuong"]}]},
                    {"name": "IoT", "code": "IOT", "courses": [{"name": "Internet of Things", "standard_folders": ["Lab", "De thi"]}]},
                ],
            }
            uploaded = client.post(
                "/api/policies/upload",
                headers={**admin, "X-Filename": "assignment-agent-policy.json", "X-Title": "Assignment Agent Policy", "Content-Type": "application/json"},
                content=json.dumps(policy_payload).encode("utf-8"),
            )
            assert uploaded.status_code == 201, uploaded.text
            assert client.post(f"/api/policies/{uploaded.json()['id']}/activate", headers=admin).status_code == 200
            assign_lecturer_csv(client, admin, [("GV001", "Nguyen Minh Anh", "AI"), ("GV002", "Giang Vien Hai", "AI")])

            move_preview = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Chuyen GV001 sang IoT"})
            assert move_preview.status_code == 200, move_preview.text
            move_body = move_preview.json()
            assert move_body["status"] == "preview"
            assert move_body["action"]["action"] == "assignment.move"
            assert move_body["preview"]["impact"]["lecturer"]["code"] == "GV001"
            assert move_body["preview"]["impact"]["assignment_impact"]["added_specializations"][0]["code"] == "IOT"
            assert move_body["preview"]["impact"]["assignment_impact"]["removed_specializations"][0]["code"] == "AI"
            assert move_body["preview"]["impact"]["virtual_tree_impact"]["rebuild"] is True
            assert move_body["preview"]["impact"]["folder_permission_impact"]["permissions_to_grant"] > 0

            move_confirm = client.post(
                "/api/policy-assistant/confirm",
                headers=admin,
                json={"message": "Chuyen GV001 sang IoT", "action": move_body["action"], "preview": move_body["preview"], "apply_now": True},
            )
            assert move_confirm.status_code == 200, move_confirm.text
            assert move_confirm.json()["applied"]["status"] == "applied"
            with database.connection() as db:
                gv001_specs = [row["name"] for row in db.execute(
                    """SELECT s.name FROM lecturer_specializations ls
                       JOIN specializations s ON s.id=ls.specialization_id
                       WHERE ls.user_code='GV001' ORDER BY s.name"""
                ).fetchall()]
                assert gv001_specs == ["IoT"]
                assert db.execute("SELECT COUNT(*) count FROM lecturer_assignment_audit_logs").fetchone()["count"] >= 1
                assert db.execute("SELECT COUNT(*) count FROM audit_logs WHERE action='lecturer_assignment.confirm'").fetchone()["count"] >= 1
                heartbeat = db.execute("SELECT * FROM automation_heartbeats WHERE workflow='lecturer_assignment'").fetchone()
                assert heartbeat and heartbeat["last_success_at"]

            assign_preview = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Gan GV002 phu trach Data Science"})
            assert assign_preview.status_code == 200, assign_preview.text
            assign_body = assign_preview.json()
            assert assign_body["action"]["action"] == "assignment.assign"
            target_codes = {item["code"] for item in assign_body["preview"]["impact"]["target_specializations"]}
            assert target_codes == {"AI", "DS"}

            assign_confirm = client.post(
                "/api/policy-assistant/confirm",
                headers=admin,
                json={"message": "Gan GV002 phu trach Data Science", "action": assign_body["action"], "preview": assign_body["preview"], "apply_now": True},
            )
            assert assign_confirm.status_code == 200, assign_confirm.text

            remove_preview = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Bo GV002 khoi AI"})
            assert remove_preview.status_code == 200, remove_preview.text
            remove_body = remove_preview.json()
            assert remove_body["action"]["action"] == "assignment.remove"
            assert {item["code"] for item in remove_body["preview"]["impact"]["target_specializations"]} == {"DS"}
            assert remove_body["preview"]["impact"]["assignment_impact"]["removed_specializations"][0]["code"] == "AI"

            missing_lecturer = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Chuyen GV999 sang IoT"})
            assert missing_lecturer.status_code == 200
            assert missing_lecturer.json()["status"] == "need_clarification"
            assert "Giang vien khong ton tai" in missing_lecturer.json()["message"]

            missing_spec = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Chuyen GV001 sang Blockchain"})
            assert missing_spec.status_code == 200
            assert missing_spec.json()["status"] == "need_clarification"
            assert "Chuyen mon khong ton tai" in missing_spec.json()["message"]

            wrong_role = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Chuyen ADMIN sang IoT"})
            assert wrong_role.status_code == 200
            assert wrong_role.json()["status"] == "need_clarification"
            assert "User khong phai lecturer" in wrong_role.json()["message"]

            final_remove = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Bo GV001 khoi IoT"})
            assert final_remove.status_code == 200, final_remove.text
            final_body = final_remove.json()
            assert final_body["status"] == "preview"
            assert final_body["preview"]["confirm_blocked_reason"]
            assert any("chuyen mon cuoi cung" in item for item in final_body["preview"]["impact"]["risk_warnings"])


def test_policy_assistant_confirm_ignores_deprecated_specialization_rows():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            policy_payload = {
                "faculty": "CNTT",
                "specializations": [
                    {"name": "AI", "code": "AI", "courses": [{"name": "Machine Learning", "standard_folders": ["De cuong", "Lab"]}]},
                    {"name": "IoT", "code": "IOT", "courses": [{"name": "Internet of Things", "standard_folders": ["Lab", "De thi"]}]},
                ],
            }
            uploaded = client.post(
                "/api/policies/upload",
                headers={**admin, "X-Filename": "assignment-agent-policy.json", "X-Title": "Assignment Agent Policy", "Content-Type": "application/json"},
                content=json.dumps(policy_payload).encode("utf-8"),
            )
            assert uploaded.status_code == 201, uploaded.text
            assert client.post(f"/api/policies/{uploaded.json()['id']}/activate", headers=admin).status_code == 200
            assign_lecturer_csv(client, admin, [("GV001", "Nguyen Minh Anh", "AI")])

            with database.transaction() as db:
                policy = db.execute("SELECT * FROM policy_files WHERE status='active'").fetchone()
                iot_spec = db.execute(
                    "SELECT * FROM specializations WHERE policy_id=? AND name='IoT' ORDER BY id LIMIT 1",
                    (policy["id"],),
                ).fetchone()
                iot_node = db.execute("SELECT * FROM folder_nodes WHERE id=?", (iot_spec["folder_node_id"],)).fetchone()
                stale_node_id = "node-stale-iot"
                stale_spec_id = "spec-zzz-stale-iot"
                db.execute(
                    "INSERT INTO folder_nodes(id,policy_id,name,parent_id,type,path,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        stale_node_id,
                        policy["id"],
                        iot_node["name"],
                        iot_node["parent_id"],
                        iot_node["type"],
                        iot_node["path"],
                        "deprecated",
                        database.now(),
                        database.now(),
                    ),
                )
                db.execute(
                    "INSERT INTO specializations(id,name,description,policy_id,folder_node_id) VALUES(?,?,?,?,?)",
                    (stale_spec_id, iot_spec["name"], iot_spec["description"], policy["id"], stale_node_id),
                )

            move_preview = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Chuyen GV001 sang IoT"})
            assert move_preview.status_code == 200, move_preview.text
            move_body = move_preview.json()
            assert move_body["status"] == "preview"
            assert move_body["action"]["specialization_id"] != "spec-zzz-stale-iot"

            move_confirm = client.post(
                "/api/policy-assistant/confirm",
                headers=admin,
                json={"message": "Chuyen GV001 sang IoT", "action": move_body["action"], "preview": move_body["preview"], "apply_now": True},
            )
            assert move_confirm.status_code == 200, move_confirm.text
            assert move_confirm.json()["applied"]["status"] == "applied"


def test_knowledge_governance_time_based_permission_phase2():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            with database.transaction() as db:
                db.execute(
                    "INSERT INTO users(code,name,role,department,password_hash,active) VALUES(?,?,?,?,?,1)",
                    ("GV002", "Giang Vien Hai", "lecturer", "CNTT", database.hash_secret("GV002")),
                )
            policy_payload = {
                "faculty": "CNTT",
                "specializations": [
                    {"name": "AI", "code": "AI", "courses": [{"name": "Toan", "standard_folders": ["De thi"]}]},
                    {"name": "Data Science", "code": "DS", "courses": [{"name": "Toan", "standard_folders": ["De thi"]}]},
                    {"name": "IoT", "code": "IOT", "courses": [{"name": "Toan", "standard_folders": ["De thi"]}]},
                ],
            }
            uploaded = client.post(
                "/api/policies/upload",
                headers={**admin, "X-Filename": "time-permission-policy.json", "X-Title": "Time Permission Policy", "Content-Type": "application/json"},
                content=json.dumps(policy_payload).encode("utf-8"),
            )
            assert uploaded.status_code == 201, uploaded.text
            assert client.post(f"/api/policies/{uploaded.json()['id']}/activate", headers=admin).status_code == 200
            assign_lecturer_csv(client, admin, [("GV001", "Nguyen Minh Anh", "AI"), ("GV002", "Giang Vien Hai", "Data Science"), ("GVNEW", "Le Thu Ha", "IoT")])
            with database.transaction() as db:
                folder = db.execute("SELECT * FROM folder_nodes WHERE name='De thi' AND type='standard_folder' AND status='active' LIMIT 1").fetchone()
                timestamp = database.now()
                db.execute(
                    """INSERT INTO documents(id,title,doc_type,topic,owner_code,visibility,current_version,content_hash,
                       created_at,updated_at,folder_path,folder_node_id,status,specialization_id,course_id,document_type)
                       VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)""",
                    (
                        "doc-exam-toan", "De thi Toan", "De thi", "Toan", "TBM01", "private",
                        "hash-exam-toan", timestamp, timestamp, folder["path"], folder["id"], "INDEXED",
                        None, folder["parent_id"], "De thi",
                    ),
                )

            future = client.post(
                "/api/policy-assistant/preview",
                headers=admin,
                json={"message": "De thi Toan chi duoc mo cho AI, Data Science, IoT vao 08:00 ngay 10/09/2026"},
            )
            assert future.status_code == 200, future.text
            future_body = future.json()
            assert future_body["status"] == "preview"
            assert future_body["action"]["action"] == "permission.time_based_release"
            impact = future_body["preview"]["impact"]
            assert impact["rule_id"].startswith("rule-")
            assert impact["rule_type"] == "time_based_permission"
            assert impact["document_type"] == "De Thi"
            assert impact["course"] == "Toan"
            assert {item["code"] for item in impact["target_specializations"]} == {"AI", "DS", "IOT"}
            assert impact["release_at"] == "2026-09-10T08:00:00+07:00"
            assert impact["permission_impact"]["documents_to_open"] == 1
            assert impact["permission_impact"]["target_lecturers"] == 3

            past = client.post(
                "/api/policy-assistant/preview",
                headers=admin,
                json={"message": "De thi Toan chi duoc mo cho AI, Data Science, IoT vao 08:00 ngay 10/09/2020"},
            )
            assert past.status_code == 200, past.text
            past_body = past.json()
            confirmed = client.post(
                "/api/policy-assistant/confirm",
                headers=admin,
                json={"message": "De thi Toan chi duoc mo cho AI, Data Science, IoT vao 08:00 ngay 10/09/2020", "action": past_body["action"], "preview": past_body["preview"], "apply_now": True},
            )
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()["applied"]["status"] == "applied"
            with database.connection() as db:
                rule = db.execute("SELECT * FROM policy_rules WHERE rule_type='time_based_permission'").fetchone()
                assert rule
                content = json.loads(rule["rule_content"])
                assert content["status"] == "applied"
                approved = db.execute(
                    """SELECT COUNT(*) count FROM access_requests
                       WHERE document_id='doc-exam-toan' AND status='approved'
                         AND source_rule_id=? AND source_rule_type='time_based_permission' AND applied_at IS NOT NULL""",
                    (rule["id"],),
                ).fetchone()["count"]
                assert approved == 3
                created_audit = db.execute("SELECT COUNT(*) count FROM audit_logs WHERE action='permission.time_based_release.created'").fetchone()["count"]
                applied_audit = db.execute("SELECT COUNT(*) count FROM audit_logs WHERE action='permission.time_based_release.applied'").fetchone()["count"]
                assert created_audit == 1
                assert applied_audit == 1
                heartbeat = db.execute("SELECT * FROM automation_heartbeats WHERE workflow='policy_activation'").fetchone()
                assert heartbeat and heartbeat["last_success_at"]

            apply_due = client.post("/internal/policy/time-based-permissions/apply-due", headers={"X-Internal-Policy-Secret": os.environ["N8N_POLICY_SECRET"]})
            assert apply_due.status_code == 200
            assert apply_due.json()["status"] == "applied"
            expire = client.post(f"/internal/policy/time-based-permissions/{rule['id']}/expire", headers={"X-Internal-Policy-Secret": os.environ["N8N_POLICY_SECRET"]})
            assert expire.status_code == 200, expire.text
            assert expire.json()["status"] == "expired"
            with database.connection() as db:
                expired = json.loads(db.execute("SELECT rule_content FROM policy_rules WHERE id=?", (rule["id"],)).fetchone()["rule_content"])
                assert expired["status"] == "expired"
                expired_audit = db.execute("SELECT COUNT(*) count FROM audit_logs WHERE action='permission.time_based_release.expired'").fetchone()["count"]
                assert expired_audit == 1


def test_knowledge_governance_advisor_phase3():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            seed_knowledge_transfer_insight_data(client, admin)

            risk_preview = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Hien tai khoa co rui ro gi?"})
            assert risk_preview.status_code == 200, risk_preview.text
            risk_body = risk_preview.json()
            assert risk_body["status"] == "preview"
            assert risk_body["action"]["action"] == "advisor.risk_analysis"
            impact = risk_body["preview"]["impact"]
            assert "risk_summary" in impact
            assert isinstance(impact["governance_score"], int)
            assert impact["high_risk_areas"]
            assert impact["dependency_warnings"]
            assert impact["recommended_actions"]
            assert impact["source"]["knowledge_transfer_dashboard"] is True
            assert risk_body["preview"]["requires_confirmation"] is False
            assert "read-only" in risk_body["preview"]["confirm_blocked_reason"]

            recommendations = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Nhung viec nao nen lam tiep?"})
            assert recommendations.status_code == 200, recommendations.text
            assert recommendations.json()["action"]["action"] == "advisor.recommendations"
            assert recommendations.json()["preview"]["impact"]["recommended_actions"]

            course_gap = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Chuyen nganh nao dang thieu tri thuc?"})
            assert course_gap.status_code == 200, course_gap.text
            assert course_gap.json()["action"]["action"] == "advisor.course_gap"
            assert course_gap.json()["preview"]["impact"]["course_gaps"]

            specialization_risk = client.post("/api/policy-assistant/preview", headers=admin, json={"message": "Rui ro chuyen nganh hien tai"})
            assert specialization_risk.status_code == 200, specialization_risk.text
            assert specialization_risk.json()["action"]["action"] == "advisor.specialization_risk"
            assert specialization_risk.json()["preview"]["impact"]["high_risk_areas"]

            confirm = client.post(
                "/api/policy-assistant/confirm",
                headers=admin,
                json={"message": "Hien tai khoa co rui ro gi?", "action": risk_body["action"], "preview": risk_body["preview"], "apply_now": True},
            )
            assert confirm.status_code == 400
            assert "read-only" in confirm.json()["detail"]


def test_governance_rule_center_read_only_rule_traceability():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            policy_payload = {
                "faculty": "CNTT",
                "specializations": [
                    {"name": "AI", "code": "AI", "courses": [
                        {"name": "Toan", "standard_folders": ["De thi"]},
                        {"name": "Ly", "standard_folders": ["De thi"]},
                    ]},
                ],
            }
            uploaded = client.post(
                "/api/policies/upload",
                headers={**admin, "X-Filename": "rule-center-policy.json", "X-Title": "Rule Center Policy", "Content-Type": "application/json"},
                content=json.dumps(policy_payload).encode("utf-8"),
            )
            assert uploaded.status_code == 201, uploaded.text
            assert client.post(f"/api/policies/{uploaded.json()['id']}/activate", headers=admin).status_code == 200
            assign_lecturer_csv(client, admin, [("GV001", "Nguyen Minh Anh", "AI")])

            with database.transaction() as db:
                timestamp = database.now()
                folders = db.execute("SELECT * FROM folder_nodes WHERE name='De thi' AND type='standard_folder' AND status='active' ORDER BY path").fetchall()
                assert len(folders) >= 2
                for index, course_name in enumerate(["Toan", "Ly"]):
                    folder = folders[index]
                    db.execute(
                        """INSERT INTO documents(id,title,doc_type,topic,owner_code,visibility,current_version,content_hash,
                           created_at,updated_at,folder_path,folder_node_id,status,specialization_id,course_id,document_type)
                           VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)""",
                        (
                            f"doc-rule-{course_name.lower()}", f"De thi {course_name}", "De thi", course_name,
                            "TBM01", "private", f"hash-rule-{course_name.lower()}", timestamp, timestamp,
                            folder["path"], folder["id"], "INDEXED", None, folder["parent_id"], "De thi",
                        ),
                    )

            def confirm_time_rule(course: str) -> str:
                preview = client.post(
                    "/api/policy-assistant/preview",
                    headers=admin,
                    json={"message": f"De thi {course} chi duoc mo cho AI vao 08:00 ngay 10/09/2020"},
                )
                assert preview.status_code == 200, preview.text
                body = preview.json()
                confirmed = client.post(
                    "/api/policy-assistant/confirm",
                    headers=admin,
                    json={"message": f"De thi {course} chi duoc mo cho AI vao 08:00 ngay 10/09/2020", "action": body["action"], "preview": body["preview"], "apply_now": True},
                )
                assert confirmed.status_code == 200, confirmed.text
                return confirmed.json()["applied"]["after"]["rule"]["id"]

            applied_rule_id = confirm_time_rule("Toan")
            expired_rule_id = confirm_time_rule("Ly")
            expire = client.post(f"/internal/policy/time-based-permissions/{expired_rule_id}/expire", headers={"X-Internal-Policy-Secret": os.environ["N8N_POLICY_SECRET"]})
            assert expire.status_code == 200, expire.text

            rule_list = client.get("/api/governance-rules", headers=admin)
            assert rule_list.status_code == 200, rule_list.text
            items = rule_list.json()["items"]
            by_id = {item["id"]: item for item in items}
            assert by_id[applied_rule_id]["status"] == "applied"
            assert by_id[applied_rule_id]["affected_documents"] >= 1
            assert by_id[applied_rule_id]["affected_users"] >= 1
            assert by_id[expired_rule_id]["status"] == "expired"
            assert by_id[expired_rule_id]["permissions_revoked"] >= 1

            applied_detail = client.get(f"/api/governance-rules/{applied_rule_id}", headers=admin)
            assert applied_detail.status_code == 200, applied_detail.text
            applied_body = applied_detail.json()
            assert applied_body["rule"]["id"] == applied_rule_id
            assert applied_body["impact"]["permissions_created"] >= 1
            assert applied_body["traceability"]["permissions_generated"]
            assert applied_body["traceability"]["affected_users"] == ["GV001"]
            assert any(item["event"] == "Applied" for item in applied_body["timeline"])
            assert any(item["action"] == "permission.time_based_release.created" for item in applied_body["audit_history"])
            assert any(item["action"] == "permission.time_based_release.applied" for item in applied_body["audit_history"])
            assert applied_body["operations"]["scheduler"]["workflow"] == "policy_activation"

            expired_detail = client.get(f"/api/governance-rules/{expired_rule_id}", headers=admin)
            assert expired_detail.status_code == 200, expired_detail.text
            expired_body = expired_detail.json()
            assert expired_body["impact"]["permissions_revoked"] >= 1
            assert expired_body["operations"]["expire_event"]["action"] == "permission.time_based_release.expired"
            assert any(item["event"] == "Expired" for item in expired_body["timeline"])


def test_global_knowledge_search_groups_and_permissions():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            lecturer = login(client, "GV001")
            seed_knowledge_transfer_insight_data(client, admin)

            with database.transaction() as db:
                ml_course = db.execute("SELECT * FROM folder_nodes WHERE name='Machine Learning' AND type='course' AND status='active'").fetchone()
                exam_folder = db.execute("SELECT * FROM folder_nodes WHERE parent_id=? AND name='De thi' AND status='active'", (ml_course["id"],)).fetchone()
                timestamp = database.now()
                db.execute(
                    """INSERT INTO documents(id,title,doc_type,topic,owner_code,visibility,current_version,content_hash,
                       created_at,updated_at,folder_path,folder_node_id,status,specialization_id,course_id,document_type)
                       VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)""",
                    (
                        "doc-rule-ml-exam", "De thi Machine Learning", "De thi", "Machine Learning",
                        "TBM01", "private", "hash-rule-ml-exam", timestamp, timestamp,
                        exam_folder["path"], exam_folder["id"], "INDEXED", None, ml_course["id"], "De thi",
                    ),
                )
                db.execute(
                    """INSERT INTO documents(id,title,doc_type,topic,owner_code,visibility,current_version,content_hash,
                       created_at,updated_at,folder_path,folder_node_id,status,specialization_id,course_id,document_type)
                       VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)""",
                    (
                        "doc-hidden-ml", "Hidden Machine Learning Notes", "Tai lieu", "Machine Learning",
                        "TBM01", "private", "hash-hidden-ml", timestamp, timestamp,
                        exam_folder["path"], exam_folder["id"], "INDEXED", None, ml_course["id"], "Tai lieu",
                    ),
                )

            preview = client.post(
                "/api/policy-assistant/preview",
                headers=admin,
                json={"message": "De thi Machine Learning chi duoc mo cho AI vao 08:00 ngay 10/09/2020"},
            )
            assert preview.status_code == 200, preview.text
            confirmed = client.post(
                "/api/policy-assistant/confirm",
                headers=admin,
                json={"message": "De thi Machine Learning chi duoc mo cho AI vao 08:00 ngay 10/09/2020", "action": preview.json()["action"], "preview": preview.json()["preview"], "apply_now": True},
            )
            assert confirmed.status_code == 200, confirmed.text
            rule_id = confirmed.json()["applied"]["after"]["rule"]["id"]

            response = client.get("/api/search/global?q=Machine%20Learning", headers=admin)
            assert response.status_code == 200, response.text
            body = response.json()
            assert any(item["id"] == "doc-kt-ai-outline" for item in body["documents"])
            assert any(item["title"] == "Machine Learning" for item in body["courses"])
            assert any("Tri tue nhan tao" in item["title"] for item in body["specializations"])
            assert any("Machine Learning" in item["title"] or "Machine Learning" in item["description"] for item in body["policy"])

            rule_search = client.get(f"/api/search/global?q={rule_id}", headers=admin)
            assert rule_search.status_code == 200
            assert any(item["id"] == rule_id for item in rule_search.json()["rules"])

            lecturer_search = client.get("/api/search/global?q=GV001", headers=admin)
            assert lecturer_search.status_code == 200
            lecturer_body = lecturer_search.json()
            assert any(item["id"] == "GV001" for item in lecturer_body["lecturers"])
            assert any("GV001" in item["title"] for item in lecturer_body["assignments"])
            assert any("GV001" in item["description"] for item in lecturer_body["audit"])

            permission_search = client.get("/api/search/global?q=Hidden%20Machine%20Learning", headers=lecturer)
            assert permission_search.status_code == 200
            assert permission_search.json()["documents"] == []

            empty = client.get("/api/search/global?q=zzzz-no-match-global", headers=admin)
            assert empty.status_code == 200
            empty_body = empty.json()
            assert all(not values for key, values in empty_body.items() if key != "query")


def test_qdrant_payload_builder_contains_permission_metadata():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with database.connection() as db:
            document = dict(db.execute("SELECT * FROM documents WHERE id='doc-de-cuong-ai'").fetchone())
            payload = services.qdrant_payload_for_chunk(db, document, "chunk-test", document["current_version"])
        expected = {
            "document_id",
            "version_no",
            "chunk_id",
            "owner_code",
            "visibility",
            "status",
            "is_deleted",
            "title",
            "topic",
            "doc_type",
            "course_id",
            "specialization_id",
            "folder_node_id",
            "classification",
        }
        assert expected <= set(payload)
        assert payload["document_id"] == "doc-de-cuong-ai"
        assert payload["chunk_id"] == "chunk-test"
        assert payload["owner_code"] == "GV001"
        assert payload["visibility"] == "public"
        assert payload["is_deleted"] is False


def test_index_document_writes_db_chunks_when_qdrant_upsert_fails(monkeypatch):
    monkeypatch.setenv("QDRANT_ENABLED", "true")
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))

        def fail_upsert(*_args, **_kwargs):
            raise RuntimeError("qdrant unavailable")

        monkeypatch.setattr(services, "upsert_vector", fail_upsert)
        with database.transaction() as db:
            services.index_document(db, "doc-de-cuong-ai", 1, "Noi dung moi cho Qdrant fallback.", force_local=True)
            chunks = database.rows(db.execute("SELECT * FROM chunks WHERE document_id='doc-de-cuong-ai'").fetchall())

        assert chunks
        assert all(chunk["provider"] != "qdrant" for chunk in chunks)


def test_reindex_qdrant_from_chunks_is_idempotent(monkeypatch):
    monkeypatch.setenv("QDRANT_ENABLED", "true")
    calls: list[tuple[str, dict]] = []

    def fake_upsert(chunk_id, _vector, payload):
        calls.append((chunk_id, payload))
        return True

    monkeypatch.setattr(services, "upsert_vector", fake_upsert)
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with database.transaction() as db:
            expected_count = db.execute("SELECT COUNT(*) count FROM chunks").fetchone()["count"]
            first = services.reindex_qdrant_from_chunks(db)
            second = services.reindex_qdrant_from_chunks(db)
            chunk_count_after = db.execute("SELECT COUNT(*) count FROM chunks").fetchone()["count"]

    assert first["processed"] == expected_count
    assert first["upserted"] == expected_count
    assert second["processed"] == expected_count
    assert second["upserted"] == expected_count
    assert chunk_count_after == expected_count
    assert {chunk_id for chunk_id, _ in calls[:expected_count]} == {chunk_id for chunk_id, _ in calls[expected_count:]}


def test_index_document_keeps_old_behavior_when_qdrant_disabled(monkeypatch):
    monkeypatch.setenv("QDRANT_ENABLED", "false")
    calls: list[str] = []

    def fake_upsert(chunk_id, _vector, _payload):
        calls.append(chunk_id)
        return True

    monkeypatch.setattr(services, "upsert_vector", fake_upsert)
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with database.transaction() as db:
            services.index_document(db, "doc-de-cuong-ai", 1, "Noi dung local khi Qdrant tat.", force_local=True)
            providers = [row["provider"] for row in db.execute("SELECT provider FROM chunks WHERE document_id='doc-de-cuong-ai'").fetchall()]

    assert calls == []
    assert providers
    assert set(providers) == {"local"}


def test_rag_database_mode_keeps_existing_behavior(monkeypatch):
    monkeypatch.setenv("RAG_RETRIEVAL_PROVIDER", "database")
    monkeypatch.setenv("QDRANT_ENABLED", "true")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Qdrant search should not be called in database mode")

    monkeypatch.setattr(services, "search_vectors", fail_if_called)
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            response = client.post("/api/search", headers=lecturer, json={"question": "RAG"})

    assert response.status_code == 200
    assert response.json()["scope"] == "public_or_owned"
    assert "citations" in response.json()


def test_rag_qdrant_mode_keeps_citation_format(monkeypatch):
    monkeypatch.setenv("RAG_RETRIEVAL_PROVIDER", "qdrant")
    monkeypatch.setenv("QDRANT_ENABLED", "true")
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        monkeypatch.setenv("QDRANT_ENABLED", "false")
        with database.transaction() as db:
            document = dict(db.execute("SELECT * FROM documents WHERE id='doc-de-cuong-ai'").fetchone())
            services.index_document(db, "doc-de-cuong-ai", 1, services.content_for(db, document), force_local=True)
            chunk = db.execute("SELECT id FROM chunks WHERE document_id='doc-de-cuong-ai' LIMIT 1").fetchone()
        monkeypatch.setenv("QDRANT_ENABLED", "true")

        def fake_search(_vector, user_code, limit=100):
            assert user_code == "GV001"
            assert limit == 100
            return [{"score": 0.98, "payload": {"document_id": "doc-de-cuong-ai", "chunk_id": chunk["id"]}}]

        monkeypatch.setattr(services, "qdrant_enabled", lambda: True)
        monkeypatch.setattr(services, "search_vectors", fake_search)
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            response = client.post("/api/search", headers=lecturer, json={"question": "noi dung gi"})

    assert response.status_code == 200
    citation = response.json()["citations"][0]
    assert citation["id"] == "doc-de-cuong-ai"
    assert {"id", "title", "topic", "version", "visibility"}.issubset(citation)


def test_rag_qdrant_permission_filter_keeps_public_or_owned(monkeypatch):
    monkeypatch.setenv("RAG_RETRIEVAL_PROVIDER", "qdrant")
    monkeypatch.setenv("QDRANT_ENABLED", "true")
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        monkeypatch.setenv("QDRANT_ENABLED", "false")
        with database.transaction() as db:
            document = dict(db.execute("SELECT * FROM documents WHERE id='doc-exam-process'").fetchone())
            services.index_document(db, "doc-exam-process", 1, services.content_for(db, document), force_local=True)
            chunk = db.execute("SELECT id FROM chunks WHERE document_id='doc-exam-process' LIMIT 1").fetchone()
        monkeypatch.setenv("QDRANT_ENABLED", "true")

        def fake_search(*_args, **_kwargs):
            return [{"score": 0.99, "payload": {"document_id": "doc-exam-process", "chunk_id": chunk["id"]}}]

        monkeypatch.setattr(services, "qdrant_enabled", lambda: True)
        monkeypatch.setattr(services, "search_vectors", fake_search)
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            response = client.post("/api/search", headers=lecturer, json={"question": "phan bien cheo de thi"})

    assert response.status_code == 200
    assert all(item["id"] != "doc-exam-process" for item in response.json()["citations"])


def test_rag_qdrant_no_results_falls_back_to_database(monkeypatch):
    monkeypatch.setenv("RAG_RETRIEVAL_PROVIDER", "qdrant")
    monkeypatch.setenv("QDRANT_ENABLED", "true")
    monkeypatch.setattr(services, "qdrant_enabled", lambda: True)
    monkeypatch.setattr(services, "search_vectors", lambda *_args, **_kwargs: [])
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            admin = login(client, "ADMIN")
            response = client.post("/api/search", headers=lecturer, json={"question": "RAG"})
            ops = client.get("/api/operations/status", headers=admin)

    assert response.status_code == 200
    assert response.json()["scope"] == "public_or_owned"
    assert response.json()["citations"]
    assert ops.json()["qdrant_fallback"]["count_last_hour"] >= 1


def test_rag_qdrant_unavailable_does_not_fail_chatbot(monkeypatch):
    monkeypatch.setenv("RAG_RETRIEVAL_PROVIDER", "qdrant")
    monkeypatch.setenv("QDRANT_ENABLED", "true")
    monkeypatch.setattr(services, "qdrant_enabled", lambda: True)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(services, "search_vectors", unavailable)
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            response = client.post("/api/search", headers=lecturer, json={"question": "RAG"})

    assert response.status_code == 200
    assert response.json()["scope"] == "public_or_owned"
    assert response.json()["citations"]


def test_audit_logs_endpoint_filters_and_paginates():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with database.transaction() as db:
            services.audit(db, "ADMIN", "document.update", "document", "doc-1", {"version": 2})
            services.audit(db, "ADMIN", "document.update", "document", "doc-2", {"version": 3})
            services.audit(db, "GV001", "rag.ask", "query", None, {"question": "RAG"})
        with TestClient(app) as client:
            admin = login(client, "ADMIN")
            response = client.get("/api/audit-logs?action=document.update&page=1&page_size=1", headers=admin)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] >= 2
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["action"] == "document.update"
    assert payload["items"][0]["resource_type"] == "document"
    assert isinstance(payload["items"][0]["detail"], dict)
    assert "document.update" in payload["options"]["actions"]


def test_audit_logs_endpoint_requires_admin():
    with tempfile.TemporaryDirectory() as directory:
        configure_temp_storage(Path(directory))
        with TestClient(app) as client:
            lecturer = login(client, "GV001")
            response = client.get("/api/audit-logs", headers=lecturer)

    assert response.status_code == 403
