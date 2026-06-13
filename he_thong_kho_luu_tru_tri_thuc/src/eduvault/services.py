from __future__ import annotations

import json
import math
import re
import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from .ai import ai_provider
from .database import BACKUP_DIR, STORAGE_DIR, database_backend, hash_secret, now, restore_database, rows, snapshot_database
from .infrastructure import delete_object, delete_vectors, publish_event, store_object, upsert_vector


def audit(db, actor: str, action: str, resource_type: str, resource_id: str | None, detail: dict | None = None):
    db.execute(
        "INSERT INTO audit_logs(actor_code,action,resource_type,resource_id,detail,created_at) VALUES(?,?,?,?,?,?)",
        (actor, action, resource_type, resource_id, json.dumps(detail or {}, ensure_ascii=False), now()),
    )


def policy_value(db, key: str, fallback: dict) -> dict:
    row = db.execute("SELECT value FROM policies WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else fallback


def v2_state_for(db, document_id: str) -> dict:
    row = db.execute("SELECT * FROM document_v2_state WHERE document_id=?", (document_id,)).fetchone()
    return dict(row) if row else {}


def set_v2_state(db, document_id: str, **changes) -> dict:
    current = v2_state_for(db, document_id)
    state = {
        "classification": current.get("classification", "private"),
        "lifecycle_status": current.get("lifecycle_status", "published"),
        "scan_status": current.get("scan_status", "clean"),
        "extraction_status": current.get("extraction_status", "completed"),
        "indexing_status": current.get("indexing_status", "completed"),
        "publish_after": current.get("publish_after"),
        **changes,
    }
    db.execute(
        """INSERT INTO document_v2_state(document_id,classification,lifecycle_status,scan_status,extraction_status,indexing_status,publish_after,updated_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(document_id) DO UPDATE SET classification=excluded.classification,lifecycle_status=excluded.lifecycle_status,
           scan_status=excluded.scan_status,extraction_status=excluded.extraction_status,indexing_status=excluded.indexing_status,
           publish_after=excluded.publish_after,updated_at=excluded.updated_at""",
        (
            document_id, state["classification"], state["lifecycle_status"], state["scan_status"],
            state["extraction_status"], state["indexing_status"], state["publish_after"], now(),
        ),
    )
    return v2_state_for(db, document_id)


def emit_outbox(db, event_type: str, aggregate_id: str, payload: dict) -> dict:
    event = {
        "id": f"evt-{uuid.uuid4().hex[:12]}",
        "event_type": event_type,
        "aggregate_id": aggregate_id,
        "payload": payload,
        "created_at": now(),
    }
    published = publish_event(event)
    db.execute(
        "INSERT INTO outbox_events(id,event_type,aggregate_id,payload,status,attempts,created_at,published_at) VALUES(?,?,?,?,?,?,?,?)",
        (
            event["id"], event_type, aggregate_id, json.dumps(payload, ensure_ascii=False),
            "published" if published else "processed_sync", 1, event["created_at"], now(),
        ),
    )
    return event


def record_object_ref(
    db, document_id: str, version_no: int, kind: str, object_key: str, raw: bytes, content_type: str
) -> dict:
    stored = store_object(object_key, raw, content_type)
    ref_id = f"obj-{uuid.uuid4().hex[:12]}"
    db.execute(
        "INSERT INTO object_refs(id,document_id,version_no,kind,provider,object_uri,object_version,checksum,size,content_type,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            ref_id, document_id, version_no, kind, stored["provider"], stored["object_uri"],
            stored["object_version"], stored["checksum"], len(raw), content_type, now(),
        ),
    )
    return dict(db.execute("SELECT * FROM object_refs WHERE id=?", (ref_id,)).fetchone())


def can_read(db, user: dict, document: dict) -> bool:
    if document["visibility"] == "public" or document["owner_code"] == user["code"]:
        return True
    state = v2_state_for(db, document["id"])
    if state.get("classification") == "confidential" and user["role"] == "head":
        return True
    approved = db.execute(
        "SELECT 1 FROM access_requests WHERE document_id=? AND requester_code=? AND status='approved'",
        (document["id"], user["code"]),
    ).fetchone()
    return bool(approved)


def list_documents(db, user: dict) -> list[dict]:
    docs = rows(db.execute("SELECT * FROM documents WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall())
    return [doc for doc in docs if can_read(db, user, doc)]


def rag_documents(db, user: dict) -> list[dict]:
    """Strict chatbot scope: public documents plus documents owned by the asker."""
    return rows(
        db.execute(
            "SELECT * FROM documents WHERE deleted_at IS NULL AND (visibility='public' OR owner_code=?) ORDER BY updated_at DESC",
            (user["code"],),
        ).fetchall()
    )


def anonymize_document(document: dict, user: dict) -> dict:
    result = dict(document)
    if result.get("visibility") == "private" and result.get("owner_code") != user["code"]:
        result["owner_code"] = "Ẩn danh"
        result["owner_anonymous"] = True
    else:
        result["owner_anonymous"] = False
    return result


def anonymize_documents(documents: list[dict], user: dict) -> list[dict]:
    return [anonymize_document(document, user) for document in documents]


def list_deleted_documents(db, user: dict) -> list[dict]:
    if user["role"] == "admin":
        return rows(db.execute("SELECT * FROM documents WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall())
    return rows(db.execute("SELECT * FROM documents WHERE deleted_at IS NOT NULL AND owner_code=? ORDER BY deleted_at DESC", (user["code"],)).fetchall())


def soft_delete_document(db, user: dict, document: dict) -> dict:
    if document["owner_code"] != user["code"]:
        raise PermissionError("Bạn không có quyền xóa tài liệu này.")
    if document.get("deleted_at"):
        raise ValueError("Tài liệu đã nằm trong thùng rác.")
    timestamp = now()
    db.execute("UPDATE documents SET deleted_at=?,updated_at=? WHERE id=?", (timestamp, timestamp, document["id"]))
    db.execute("DELETE FROM chunks WHERE document_id=?", (document["id"],))
    delete_vectors(document["id"])
    audit(db, user["code"], "document.delete", "document", document["id"])
    return {"id": document["id"], "deleted_at": timestamp, "status": "trashed"}


def restore_deleted_document(db, user: dict, document: dict) -> dict:
    if document["owner_code"] != user["code"]:
        raise PermissionError("Bạn không có quyền khôi phục tài liệu này.")
    if not document.get("deleted_at"):
        raise ValueError("Tài liệu không nằm trong thùng rác.")
    db.execute("UPDATE documents SET deleted_at=NULL,updated_at=? WHERE id=?", (now(), document["id"]))
    restored = dict(db.execute("SELECT * FROM documents WHERE id=?", (document["id"],)).fetchone())
    index_document(db, restored["id"], restored["current_version"], content_for(db, restored))
    audit(db, user["code"], "document.restore", "document", document["id"])
    return restored


def permanently_delete_document(db, user: dict, document: dict) -> dict:
    if user["role"] != "admin":
        raise PermissionError("Chỉ quản trị viên được xóa vĩnh viễn.")
    if not document.get("deleted_at"):
        raise ValueError("Cần chuyển tài liệu vào thùng rác trước.")
    assets = rows(db.execute("SELECT original_path FROM file_assets WHERE document_id=?", (document["id"],)).fetchall())
    versions = rows(db.execute("SELECT storage_path FROM versions WHERE document_id=?", (document["id"],)).fetchall())
    objects = rows(db.execute("SELECT object_uri FROM object_refs WHERE document_id=?", (document["id"],)).fetchall())
    db.execute("DELETE FROM chunks WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM object_refs WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM document_v2_state WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM file_assets WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM versions WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM access_requests WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM documents WHERE id=?", (document["id"],))
    for item in assets + versions:
        path = Path(item.get("original_path") or item.get("storage_path"))
        if path.exists() and path.is_file():
            path.unlink()
    for item in objects:
        delete_object(item["object_uri"])
    delete_vectors(document["id"])
    audit(db, user["code"], "document.purge", "document", document["id"])
    return {"id": document["id"], "status": "deleted_permanently"}


def content_for(db, document: dict) -> str:
    row = db.execute(
        "SELECT storage_path FROM versions WHERE document_id=? AND version_no=?",
        (document["id"], document["current_version"]),
    ).fetchone()
    return Path(row["storage_path"]).read_text(encoding="utf-8") if row else ""


def guess_metadata(filename: str, content: str, instructions: str | None = None) -> dict:
    text = f"{filename} {content}".lower()
    topic = "Khác"
    for candidate, keywords in {
        "Trí tuệ nhân tạo": ["ai", "rag", "embedding", "học máy", "trí tuệ"],
        "Lập trình": ["python", "lập trình", "code"],
        "Khảo thí": ["đề thi", "khảo thí", "chấm thi"],
        "Quy trình nội bộ": ["quy trình", "thủ tục", "biên bản"],
    }.items():
        if any(keyword in text for keyword in keywords):
            topic = candidate
            break
    doc_type = "Tài liệu"
    for candidate in ["Đề cương", "Quy trình", "Biên bản", "Học liệu"]:
        if candidate.lower() in text:
            doc_type = candidate
            break
    title = Path(filename).stem.replace("_", " ").replace("-", " ").strip().title()
    fallback = {
        "title": title or "Tài liệu chưa đặt tên", "topic": topic, "doc_type": doc_type,
        "summary": content[:300].strip(), "keywords": [word for word in re.findall(r"\w+", topic.lower()) if len(word) > 2],
    }
    return ai_provider.metadata(filename, content, fallback, instructions)


def safe_segment(value: str) -> str:
    return (re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value).strip(" .-")[:100] or "Khác")


def suggest_folder(db, user: dict, metadata: dict) -> str:
    row = db.execute("SELECT value FROM policies WHERE key='storage_rules'").fetchone()
    policy = json.loads(row["value"]) if row else {}
    template = policy.get("naming", "{department}/{topic}/{doc_type}/{visibility}")
    values = {**metadata, "department": user["department"], "owner_code": user["code"]}
    result = template
    for key in ("department", "topic", "doc_type", "visibility", "owner_code", "title"):
        result = result.replace(f"{{{key}}}", safe_segment(str(values.get(key, "Khác"))))
    return "/".join(safe_segment(part) for part in result.replace("\\", "/").split("/") if part)


def create_document(db, user: dict, payload: dict) -> dict:
    content = payload.get("content", "").strip()
    digest = hash_secret(content)
    duplicate = db.execute("SELECT id,title FROM documents WHERE content_hash=?", (digest,)).fetchone()
    if duplicate:
        raise ValueError(f"Nội dung trùng với tài liệu: {duplicate['title']}")
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    timestamp = now()
    path = STORAGE_DIR / doc_id / "v1.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    folder_path = payload.get("folder_path") or suggest_folder(db, user, payload)
    db.execute(
        "INSERT INTO documents(id,title,doc_type,topic,owner_code,visibility,current_version,content_hash,created_at,updated_at,folder_path) VALUES(?,?,?,?,?,?,1,?,?,?,?)",
        (doc_id, payload["title"], payload["doc_type"], payload["topic"], user["code"], payload["visibility"], digest, timestamp, timestamp, folder_path),
    )
    db.execute(
        "INSERT INTO versions VALUES(?,?,?,?,?,?,?)",
        (f"ver-{uuid.uuid4().hex[:12]}", doc_id, 1, str(path), digest, user["code"], timestamp),
    )
    classification = "confidential" if "đề thi" in f"{payload['title']} {payload['doc_type']} {payload['topic']}".lower() else payload["visibility"]
    set_v2_state(db, doc_id, classification=classification, indexing_status="processing")
    record_object_ref(db, doc_id, 1, "extracted_text", f"documents/{doc_id}/versions/1/content.txt", content.encode("utf-8"), "text/plain")
    emit_outbox(db, "document.created", doc_id, {"version_no": 1, "classification": classification})
    audit(db, user["code"], "document.create", "document", doc_id, {"title": payload["title"]})
    index_document(db, doc_id, 1, content)
    sync_document(db, doc_id, path)
    return dict(db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())


def save_file_asset(db, document_id: str, version_no: int, filename: str, mime_type: str, raw: bytes) -> dict:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "upload.bin"
    document = db.execute("SELECT folder_path FROM documents WHERE id=?", (document_id,)).fetchone()
    folder = Path(*document["folder_path"].split("/")) if document and document["folder_path"] else Path("Unsorted")
    path = STORAGE_DIR / "repository" / folder / document_id / f"v{version_no}_{safe_name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    asset_id = f"asset-{uuid.uuid4().hex[:12]}"
    db.execute(
        "INSERT INTO file_assets VALUES(?,?,?,?,?,?,?,?)",
        (asset_id, document_id, version_no, filename, str(path), mime_type, len(raw), now()),
    )
    record_object_ref(
        db, document_id, version_no, "original",
        f"documents/{document_id}/versions/{version_no}/original/{safe_name}", raw, mime_type,
    )
    emit_outbox(db, "document.original_stored", document_id, {"version_no": version_no, "filename": filename})
    return dict(db.execute("SELECT * FROM file_assets WHERE id=?", (asset_id,)).fetchone())


def extract_text(filename: str, mime_type: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".xml", ".html", ".log", ".py", ".js", ".ts"} or mime_type.startswith("text/"):
        for encoding in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))
            return "\n".join(text.text for text in root.iter() if text.tag.endswith("}t") and text.text)
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
            pass
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw))
            extracted = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if extracted:
                return extracted
        except Exception:
            pass
        try:
            import fitz
            pdf = fitz.open(stream=raw, filetype="pdf")
            images = [page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png") for page in pdf[:10]]
            ocr_text = ai_provider.ocr_images(images).strip()
            if ocr_text:
                return ocr_text
        except Exception:
            pass
        return f"[PDF scan chưa OCR được: {filename}]"
    return f"[File gốc: {filename}] Nội dung chưa được trích xuất. Cần cấu hình parser/OCR cho định dạng {suffix or mime_type}."


def update_document(db, user: dict, document: dict, payload: dict) -> dict:
    if document["owner_code"] != user["code"]:
        raise PermissionError("Bạn không có quyền cập nhật tài liệu này.")
    content = payload.get("content", "").strip()
    version = document["current_version"] + 1
    path = STORAGE_DIR / document["id"] / f"v{version}.txt"
    path.write_text(content, encoding="utf-8")
    digest = hash_secret(content)
    db.execute(
        "INSERT INTO versions VALUES(?,?,?,?,?,?,?)",
        (f"ver-{uuid.uuid4().hex[:12]}", document["id"], version, str(path), digest, user["code"], now()),
    )
    folder_path = payload.get("folder_path") or document.get("folder_path") or suggest_folder(db, user, payload)
    db.execute(
        "UPDATE documents SET title=?,doc_type=?,topic=?,visibility=?,current_version=?,content_hash=?,updated_at=?,folder_path=? WHERE id=?",
        (payload["title"], payload["doc_type"], payload["topic"], payload["visibility"], version, digest, now(), folder_path, document["id"]),
    )
    classification = "confidential" if "đề thi" in f"{payload['title']} {payload['doc_type']} {payload['topic']}".lower() else payload["visibility"]
    set_v2_state(db, document["id"], classification=classification, indexing_status="processing")
    record_object_ref(db, document["id"], version, "extracted_text", f"documents/{document['id']}/versions/{version}/content.txt", content.encode("utf-8"), "text/plain")
    emit_outbox(db, "document.version_created", document["id"], {"version_no": version})
    audit(db, user["code"], "document.update", "document", document["id"], {"version": version})
    index_document(db, document["id"], version, content)
    sync_document(db, document["id"], path)
    return dict(db.execute("SELECT * FROM documents WHERE id=?", (document["id"],)).fetchone())


def rollback_document(db, user: dict, document: dict, target: int) -> dict:
    if document["owner_code"] != user["code"]:
        raise PermissionError("Bạn không có quyền rollback tài liệu này.")
    source = db.execute("SELECT storage_path FROM versions WHERE document_id=? AND version_no=?", (document["id"], target)).fetchone()
    if not source:
        raise ValueError("Phiên bản không tồn tại.")
    content = Path(source["storage_path"]).read_text(encoding="utf-8")
    return update_document(db, user, document, {**document, "content": content})


def ask(db, user: dict, question: str) -> dict:
    allowed = {document["id"]: document for document in rag_documents(db, user)}
    query_vectors: dict[str, list[float]] = {}
    vector_matches = []
    for chunk in db.execute("SELECT * FROM chunks").fetchall():
        document = allowed.get(chunk["document_id"])
        if not document:
            continue
        provider = chunk["provider"]
        if provider not in query_vectors:
            query_vectors[provider] = ai_provider.embed(question, force_local=provider == "local")
        query_vector = query_vectors[provider]
        vector = json.loads(chunk["vector"])
        similarity = sum(a * b for a, b in zip(query_vector, vector))
        vector_matches.append((similarity, document, chunk["content"]))
    vector_matches.sort(key=lambda item: item[0], reverse=True)
    if vector_matches and vector_matches[0][0] > 0:
        matches = vector_matches[:3]
    else:
        matches = []
    words = {word for word in re.findall(r"\w+", question.lower(), re.UNICODE) if len(word) > 2}
    scored = []
    for document in allowed.values():
        content = content_for(db, document)
        searchable = f"{document['title']} {document['topic']} {document['doc_type']} {content}".lower()
        score = sum(word in searchable for word in words)
        if score:
            scored.append((score, document, content))
    if not matches:
        scored.sort(key=lambda item: item[0], reverse=True)
        matches = scored[:3]
    audit(db, user["code"], "rag.ask", "query", None, {"question": question, "matches": len(matches), "scope": "public_or_owned"})
    if not matches:
        return {
            "answer": (
                "Mình chưa tìm thấy nội dung phù hợp trong những tài liệu bạn được phép xem.\n\n"
                "Bạn có thể thử dùng **tên học phần**, **chủ đề**, hoặc một cụm từ cụ thể hơn.\n\n"
                "### Bạn có thể hỏi tiếp\n\n"
                "- Tìm tài liệu theo chủ đề\n"
                "- Giải thích một thuật ngữ cụ thể\n"
                "- Liệt kê tài liệu tôi có thể xem"
            ),
            "citations": [],
            "scope": "public_or_owned",
        }
    fallback = conversational_fallback(question, matches)
    prompts = policy_value(db, "ai_prompts", {})
    answer = ai_provider.answer(question, [{"title": document["title"], "content": content} for _, document, content in matches], fallback, prompts.get("answer_instructions"))
    answer = ensure_conversational_format(answer, question)
    return {
        "answer": answer,
        "citations": [{"id": d["id"], "title": d["title"], "topic": d["topic"], "version": d["current_version"], "visibility": d["visibility"]} for _, d, _ in matches],
        "scope": "public_or_owned",
        "pipeline": ["parse", "chunk", "embed", "vector_store", "permission_filter", "retrieve", "answer"],
    }


def conversational_fallback(question: str, matches: list[tuple]) -> str:
    highlights = []
    for _, document, content in matches[:3]:
        sentences = [
            part.strip()
            for part in re.split(r"\n+|(?<=[.!?])\s+", content)
            if part.strip() and not part.strip().startswith("[")
        ]
        detail = sentences[0][:240] if sentences else f"Tài liệu tập trung vào {document['topic']}."
        highlights.append((document["title"], detail))

    topic_lines = "\n\n".join(
        f"- **{title}**: {detail}" for title, detail in highlights
    )
    attention = "\n\n".join(
        f"⚠️ Chú ý phần **{document['topic']}** trong tài liệu *{document['title']}*."
        for _, document, _ in matches[:2]
    )
    return (
        "📚 Mình đã đọc các tài liệu liên quan và đây là phần hữu ích nhất cho câu hỏi của bạn.\n\n"
        "### Nội dung trọng tâm\n\n"
        f"{topic_lines}\n\n"
        "### Những phần cần chú ý\n\n"
        f"{attention}\n\n"
        "### Gợi ý học tập\n\n"
        "✅ Đọc lần lượt từng ý trọng tâm, sau đó tự diễn giải lại bằng lời của bạn.\n\n"
        f"✅ Đối chiếu các ý trên với câu hỏi **{question.strip()}** để xác định phần cần đào sâu.\n\n"
        "### Bạn có thể hỏi tiếp\n\n"
        "- Giải thích kỹ hơn từng ý\n"
        "- Tạo câu hỏi ôn tập từ nội dung này\n"
        "- So sánh các tài liệu liên quan\n"
        "- Đề xuất lộ trình học"
    )


def ensure_conversational_format(answer: str, question: str) -> str:
    cleaned = re.split(
        r"\n#{0,3}\s*(?:📄\s*)?(?:Nguồn tham khảo|Nguồn tài liệu|Tài liệu tham khảo)\s*:?",
        answer.strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    required = (
        "### Nội dung trọng tâm",
        "### Những phần cần chú ý",
        "### Gợi ý học tập",
        "### Bạn có thể hỏi tiếp",
    )
    if all(section in cleaned for section in required):
        return cleaned
    return (
        "📚 Mình đã đọc tài liệu và chọn ra những ý hữu ích nhất cho bạn.\n\n"
        "### Nội dung trọng tâm\n\n"
        f"{cleaned}\n\n"
        "### Những phần cần chú ý\n\n"
        "⚠️ Hãy đối chiếu các ý trên với **ngữ cảnh và phạm vi áp dụng** trong tài liệu.\n\n"
        "### Gợi ý học tập\n\n"
        f"✅ Thử diễn giải lại câu trả lời cho câu hỏi **{question.strip()}** bằng lời của bạn.\n\n"
        "✅ Chọn một phần chưa rõ và hỏi sâu hơn thay vì đọc lại toàn bộ.\n\n"
        "### Bạn có thể hỏi tiếp\n\n"
        "- Giải thích kỹ hơn một phần\n"
        "- Tạo câu hỏi ôn tập từ nội dung này\n"
        "- So sánh các tài liệu liên quan\n"
        "- Đề xuất nội dung nên học tiếp"
    )


def index_document(db, document_id: str, version_no: int, content: str, force_local: bool = False) -> None:
    db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
    delete_vectors(document_id)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|(?<=[.!?])\s+", content) if part.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs or [content]:
        if len(current) + len(paragraph) > 1200 and current:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current} {paragraph}".strip()
    if current:
        chunks.append(current)
    for chunk in chunks[:100]:
        chunk_id = f"chunk-{uuid.uuid4().hex[:12]}"
        vector = ai_provider.embed(chunk, force_local=force_local)
        indexed_external = upsert_vector(
            chunk_id, vector, {"document_id": document_id, "version_no": version_no}
        )
        db.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?)",
            (
                chunk_id, document_id, version_no, chunk, json.dumps(vector),
                "qdrant" if indexed_external else ("local" if force_local else ai_provider.mode), now(),
            ),
        )
    set_v2_state(db, document_id, indexing_status="completed")
    emit_outbox(db, "document.indexed", document_id, {"version_no": version_no, "chunks": len(chunks[:100])})


def create_backup(db, user: dict) -> dict:
    backup_id = f"backup-{uuid.uuid4().hex[:10]}"
    target = BACKUP_DIR / backup_id
    target.mkdir(parents=True)
    database_file = target / ("eduvault.mysql.json" if database_backend() == "mysql" else "eduvault.db")
    snapshot_database(db, database_file)
    shutil.copytree(STORAGE_DIR, target / "storage")
    db.execute("INSERT INTO backup_logs VALUES(?,?,?,?,?)", (backup_id, str(target), "success", user["code"], now()))
    audit(db, user["code"], "backup.create", "backup", backup_id)
    return dict(db.execute("SELECT * FROM backup_logs WHERE id=?", (backup_id,)).fetchone())


def restore_backup(db, user: dict, backup_id: str) -> dict:
    backup = db.execute("SELECT * FROM backup_logs WHERE id=? AND status='success'", (backup_id,)).fetchone()
    if not backup:
        raise ValueError("Không tìm thấy bản backup hợp lệ.")
    source_dir = Path(backup["storage_path"])
    source_db = source_dir / ("eduvault.mysql.json" if database_backend() == "mysql" else "eduvault.db")
    source_storage = source_dir / "storage"
    if not source_db.exists() or not source_storage.exists():
        raise ValueError("Bản backup thiếu database hoặc storage.")

    safety_id = f"pre-restore-{uuid.uuid4().hex[:8]}"
    safety_dir = BACKUP_DIR / safety_id
    safety_dir.mkdir(parents=True)
    safety_db = safety_dir / ("eduvault.mysql.json" if database_backend() == "mysql" else "eduvault.db")
    snapshot_database(db, safety_db)
    shutil.copytree(STORAGE_DIR, safety_dir / "storage")

    restore_database(db, source_db)
    shutil.copytree(source_storage, STORAGE_DIR, dirs_exist_ok=True)
    audit(db, user["code"], "backup.restore", "backup", backup_id, {"safety_backup": safety_id})
    return {"restored": backup_id, "safety_backup": safety_id, "status": "success"}


def sync_document(db, document_id: str, source: Path, storage_id: str | None = None) -> list[dict]:
    results = []
    query = "SELECT * FROM external_storages WHERE enabled=1"
    params = ()
    if storage_id:
        query += " AND id=?"
        params = (storage_id,)
    for storage in db.execute(query, params).fetchall():
        target_dir = Path(storage["location"]) / document_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        shutil.copy2(source, target)
        timestamp = now()
        log_id = f"sync-{uuid.uuid4().hex[:10]}"
        db.execute("INSERT INTO sync_logs VALUES(?,?,?,?,?,?)", (log_id, storage["id"], document_id, "success", str(target), timestamp))
        db.execute("UPDATE external_storages SET last_sync_at=?,last_status='success' WHERE id=?", (timestamp, storage["id"]))
        results.append({"storage": storage["name"], "status": "success", "path": str(target)})
    return results


def knowledge_summary(db, user: dict, *, topic: str | None = None, doc_type: str | None = None) -> dict:
    selected = []
    for document in list_documents(db, user):
        if topic and topic.lower() not in document["topic"].lower() and topic.lower() not in document["title"].lower():
            continue
        if doc_type and doc_type.lower() not in document["doc_type"].lower():
            continue
        selected.append({**document, "content": content_for(db, document)})
    return {
        "summary": " ".join(item["content"] for item in selected[:5]) or "Chưa có đủ tài liệu để tổng hợp.",
        "documents": [{"id": item["id"], "title": item["title"], "topic": item["topic"], "doc_type": item["doc_type"]} for item in selected],
    }


def quality_report(db) -> dict:
    documents = rows(db.execute("SELECT * FROM documents").fetchall())
    hashes: dict[str, list[dict]] = {}
    for document in documents:
        hashes.setdefault(document["content_hash"], []).append(document)
    duplicates = [[item["title"] for item in group] for group in hashes.values() if len(group) > 1]
    stale = [doc for doc in documents if doc["updated_at"] < "2025-06-09"]
    missing = []
    for course in db.execute("SELECT * FROM courses").fetchall():
        required = json.loads(course["required_doc_types"])
        available = {doc["doc_type"] for doc in documents if course["name"].lower() in f"{doc['topic']} {doc['title']}".lower()}
        absent = [item for item in required if item not in available]
        if absent:
            missing.append({"course_code": course["code"], "course": course["name"], "missing": absent})
    return {"stale": stale, "duplicates": duplicates, "missing_course_documents": missing}


def usage_report(db) -> dict:
    actions = rows(db.execute("SELECT action,COUNT(*) count FROM audit_logs GROUP BY action ORDER BY count DESC").fetchall())
    return {
        "actions": actions,
        "documents": db.execute("SELECT COUNT(*) count FROM documents").fetchone()["count"],
        "users": db.execute("SELECT COUNT(*) count FROM users WHERE active=1").fetchone()["count"],
        "queries": db.execute("SELECT COUNT(*) count FROM audit_logs WHERE action='rag.ask'").fetchone()["count"],
        "transfers": db.execute("SELECT COUNT(*) count FROM transfers").fetchone()["count"],
    }


def compliance_report(db) -> dict:
    storages = rows(db.execute("SELECT * FROM external_storages WHERE enabled=1").fetchall())
    successful = [item for item in storages if item["last_status"] in {"ready", "success"}]
    offsite = [item for item in successful if item["provider"] != "local"]
    policy = policy_value(db, "backup_321", {"copies": 3, "media": 2, "offsite": 1})
    return {
        "compliant": len(successful) >= policy["copies"] and len({item["provider"] for item in successful}) >= policy["media"] and len(offsite) >= policy["offsite"],
        "copies": len(successful),
        "media": len({item["provider"] for item in successful}),
        "offsite": len(offsite),
        "required": policy,
        "storages": storages,
    }
