import tempfile
import zipfile
import os
from io import BytesIO
from pathlib import Path

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
    response = client.post("/api/auth/login", json={"code": code, "password": code})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


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
            assert client.get("/api/reports/usage", headers=head).status_code == 200
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

            assert client.get(f"/api/documents/{document_id}", headers=head).status_code == 200
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
