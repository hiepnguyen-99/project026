from __future__ import annotations

import json
import hashlib
import math
import re
import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from .ai import ai_provider
from .database import BACKUP_DIR, STORAGE_DIR, database_backend, hash_secret, now, restore_database, rows, snapshot_database, map_document_type_to_standard_folder
from .infrastructure import delete_object, delete_vectors, publish_event, store_object, upsert_vector


STANDARD_FOLDERS = [
    "Đề cương môn học",
    "Bài giảng",
    "Slide",
    "Lab",
    "Bài tập",
    "Đề thi",
    "Đáp án",
    "Tài liệu tham khảo",
]

DOCUMENT_TYPES = [
    "Đề cương môn học",
    "Kế hoạch giảng dạy",
    "Bài giảng",
    "Slide",
    "Giáo trình",
    "Sách tham khảo",
    "Lab",
    "Bài tập",
    "Đồ án",
    "Đề thi",
    "Đáp án",
    "Ngân hàng câu hỏi",
    "Nghiên cứu khoa học",
    "Tài liệu khác",
]

PROCESSING_JOB_TYPES = ["OCR", "CHUNKING", "EMBEDDING", "INDEXING", "METADATA_EXTRACTION"]

EMPTY_POLICY_TREE = {
    "faculty": "",
    "specializations": [],
    "courses": [],
    "standard_folders": STANDARD_FOLDERS,
}


def audit(db, actor: str, action: str, resource_type: str, resource_id: str | None, detail: dict | None = None):
    db.execute(
        "INSERT INTO audit_logs(actor_code,action,resource_type,resource_id,detail,created_at) VALUES(?,?,?,?,?,?)",
        (actor, action, resource_type, resource_id, json.dumps(detail or {}, ensure_ascii=False), now()),
    )


def policy_value(db, key: str, fallback: dict) -> dict:
    row = db.execute("SELECT value FROM policies WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else fallback


def _clean_node_name(value: object) -> str:
    name = str(value or "").strip().strip("-•* \t\r\n\"'")
    name = re.sub(r"\s+", " ", name)
    if not name:
        return ""
    technical = re.fullmatch(r"(node|spec|policy|ls)-[0-9a-fA-F-]+", name)
    if technical or name.lower() in {"thu muc", "thư mục", "folder", "default", "none", "null"}:
        return ""
    return name


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _folder_names(value: object) -> list[str]:
    names = [_clean_node_name(item) for item in _as_list(value)]
    return [name for name in names if name]


def _course_from_item(item: object, fallback_name: str = "") -> dict | None:
    if isinstance(item, str):
        name = _clean_node_name(item)
        code = ""
        description = ""
        folders = STANDARD_FOLDERS
    elif isinstance(item, dict):
        name = _clean_node_name(item.get("name") or item.get("title") or item.get("course") or fallback_name)
        code = _clean_node_name(item.get("code"))
        description = str(item.get("description") or "").strip()
        folders = _folder_names(item.get("standard_folders") or item.get("folders") or item.get("folder_names")) or STANDARD_FOLDERS
    else:
        return None
    if not name:
        return None
    return {"name": name, "code": code, "description": description, "standard_folders": folders}


def normalize_policy_tree(data: dict) -> dict:
    raw_faculty = data.get("faculty") or data.get("department") or data.get("khoa")
    faculty_code = ""
    if isinstance(raw_faculty, dict):
        faculty = _clean_node_name(raw_faculty.get("name") or raw_faculty.get("title"))
        faculty_code = _clean_node_name(raw_faculty.get("code"))
    else:
        faculty = _clean_node_name(raw_faculty)
    default_folders = _folder_names(data.get("standard_folders") or data.get("folders")) or STANDARD_FOLDERS
    specializations: list[dict] = []

    for item in _as_list(data.get("specializations") or data.get("majors") or data.get("groups")):
        if not isinstance(item, dict):
            name = _clean_node_name(item)
            description = ""
            courses = []
        else:
            name = _clean_node_name(item.get("name") or item.get("title") or item.get("specialization"))
            description = str(item.get("description") or "").strip()
            courses = [_course_from_item(course) for course in _as_list(item.get("courses") or item.get("subjects"))]
            courses = [course for course in courses if course]
            legacy_folders = _folder_names(item.get("folders") or item.get("standard_folders"))
            if not courses and name:
                courses = [{"name": name, "standard_folders": legacy_folders or default_folders}]
        if name and courses:
            specializations.append({"name": name, "description": description, "courses": courses})

    loose_courses = [_course_from_item(course) for course in _as_list(data.get("courses"))]
    loose_courses = [course for course in loose_courses if course]
    if loose_courses:
        target_name = _clean_node_name(data.get("specialization") or data.get("group")) or "Chuyên môn chung"
        existing = next((item for item in specializations if item["name"] == target_name), None)
        if existing:
            existing["courses"].extend(loose_courses)
        else:
            specializations.append({"name": target_name, "description": "", "courses": loose_courses})

    seen_specs: set[str] = set()
    clean_specs: list[dict] = []
    for spec in specializations:
        spec_key = spec["name"].casefold()
        if spec_key in seen_specs:
            continue
        seen_specs.add(spec_key)
        seen_courses: set[str] = set()
        courses = []
        for course in spec["courses"]:
            course_key = course["name"].casefold()
            if course_key in seen_courses:
                continue
            seen_courses.add(course_key)
            folders = _folder_names(course.get("standard_folders")) or default_folders
            courses.append({
                "name": course["name"],
                "code": course.get("code", ""),
                "description": course.get("description", ""),
                "standard_folders": folders,
            })
        if courses:
            clean_specs.append({"name": spec["name"], "description": spec.get("description", ""), "courses": courses})

    return {"faculty": faculty, "faculty_code": faculty_code, "specializations": clean_specs, "standard_folders": default_folders}


def _try_parse_yaml_like(text: str) -> dict | None:
    faculty = ""
    specializations: list[dict] = []
    current_spec: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if lowered.startswith(("faculty:", "department:", "khoa:")):
            faculty = _clean_node_name(line.split(":", 1)[1])
        elif lowered.startswith(("specialization:", "nhom chuyen mon:", "nhóm chuyên môn:", "chuyen nganh:", "chuyên ngành:")):
            if current_spec:
                specializations.append(current_spec)
            current_spec = {"name": _clean_node_name(line.split(":", 1)[1]), "courses": []}
        elif lowered.startswith(("course:", "hoc phan:", "học phần:", "mon hoc:", "môn học:", "- course:", "- hoc phan:", "- học phần:")) and current_spec is not None:
            current_spec["courses"].append({"name": _clean_node_name(line.split(":", 1)[1]), "standard_folders": STANDARD_FOLDERS})
        elif line.startswith("-") and current_spec is not None:
            name = _clean_node_name(line[1:])
            if name:
                current_spec["courses"].append({"name": name, "standard_folders": STANDARD_FOLDERS})
    if current_spec:
        specializations.append(current_spec)
    if faculty and specializations:
        return {"faculty": faculty, "specializations": specializations}
    return None


def parse_policy_tree(raw_text: str) -> dict:
    text = raw_text.strip()
    if not text:
        raise ValueError("Policy khong co noi dung de sinh Master Folder Tree.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _try_parse_yaml_like(text)
    if not data:
        faculty = ""
        specs: list[dict] = []
        current_spec: dict | None = None
        for raw_line in text.splitlines():
            line = raw_line.strip(" -\t")
            if not line:
                continue
            lowered = line.lower()
            if any(token in lowered for token in ("khoa", "faculty", "department")) and ":" in line:
                label, value = line.split(":", 1)
                faculty = _clean_node_name(value or label)
            elif ":" in line:
                label, value = line.split(":", 1)
                if current_spec:
                    specs.append(current_spec)
                courses = [_course_from_item(item) for item in re.split(r",|;", value) if _clean_node_name(item)]
                current_spec = {"name": _clean_node_name(label), "courses": [course for course in courses if course]}
        if current_spec:
            specs.append(current_spec)
        data = {"faculty": faculty, "specializations": specs}
    parsed = ai_provider.policy_tree(text, normalize_policy_tree(data if isinstance(data, dict) else {}))
    normalized = normalize_policy_tree(parsed if isinstance(parsed, dict) else {})
    if not normalized["faculty"] or not normalized["specializations"]:
        raise ValueError("Không tìm thấy danh sách chuyên môn trong Policy.")
    return normalized


def tree_node_public(row: dict, children: list[dict] | None = None) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "parent_id": row.get("parent_id"),
        "type": row["type"],
        "policy_id": row["policy_id"],
        "path": row["path"],
        "status": row.get("status", "active"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "children": children or [],
    }


def build_tree_from_rows(nodes: list[dict], root_name: str | None = None) -> dict:
    by_parent: dict[str | None, list[dict]] = {}
    known_ids = {node["id"] for node in nodes}
    for node in nodes:
        parent_id = node.get("parent_id") if node.get("parent_id") in known_ids else None
        by_parent.setdefault(parent_id, []).append(node)
    type_order = {"faculty": 0, "department": 0, "specialization": 1, "course": 2, "standard_folder": 3, "folder": 3}
    for siblings in by_parent.values():
        siblings.sort(key=lambda item: (type_order.get(item["type"], 9), item["name"].lower()))

    def build(node: dict) -> dict:
        return tree_node_public(node, [build(child) for child in by_parent.get(node["id"], [])])

    roots = [build(node) for node in by_parent.get(None, [])]
    if root_name is not None:
        return {"name": root_name, "children": roots}
    return roots[0] if len(roots) == 1 else {"name": "Master Folder Tree", "children": roots}


def active_policy(db) -> dict | None:
    row = db.execute("SELECT * FROM policy_files WHERE status='active' ORDER BY activated_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def create_policy_file(db, user: dict, title: str, filename: str, raw: bytes, mime_type: str) -> dict:
    text = extract_text(filename, mime_type, raw)
    parsed = parse_policy_tree(text)
    policy_id = f"policy-{uuid.uuid4().hex[:12]}"
    policy_dir = STORAGE_DIR / "policies"
    policy_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(filename)
    file_path = policy_dir / f"{policy_id}_{safe_name}"
    file_path.write_bytes(raw)
    timestamp = now()
    db.execute(
        "INSERT INTO policy_files(id,title,file_path,status,raw_text,parsed_json,created_by,created_at,activated_at) VALUES(?,?,?,?,?,?,?,?,NULL)",
        (policy_id, title, str(file_path), "draft", text, json.dumps(parsed, ensure_ascii=False), user["code"], timestamp),
    )
    audit(db, user["code"], "policy_file.upload", "policy", policy_id, {"filename": filename})
    return dict(db.execute("SELECT * FROM policy_files WHERE id=?", (policy_id,)).fetchone())


def activate_policy_file(db, user: dict, policy_id: str) -> dict:
    policy = db.execute("SELECT * FROM policy_files WHERE id=?", (policy_id,)).fetchone()
    if not policy:
        raise ValueError("Policy khong ton tai.")
    parsed = json.loads(policy["parsed_json"])
    timestamp = now()
    db.execute("UPDATE policy_files SET status='archived' WHERE status='active' AND id<>?", (policy_id,))
    db.execute("UPDATE policy_files SET status='active',activated_at=? WHERE id=?", (timestamp, policy_id))
    db.execute("UPDATE folder_nodes SET status='deprecated',updated_at=? WHERE status='active'", (timestamp,))

    faculty_id = f"node-{uuid.uuid4().hex[:12]}"
    faculty = parsed["faculty"]
    db.execute(
        "INSERT INTO folder_nodes(id,policy_id,name,parent_id,type,path,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (faculty_id, policy_id, faculty, None, "faculty", faculty, "active", timestamp, timestamp),
    )
    for spec in parsed["specializations"]:
        spec_id = f"node-{uuid.uuid4().hex[:12]}"
        spec_path = f"{faculty}/{spec['name']}"
        db.execute(
            "INSERT INTO folder_nodes(id,policy_id,name,parent_id,type,path,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (spec_id, policy_id, spec["name"], faculty_id, "specialization", spec_path, "active", timestamp, timestamp),
        )
        specialization_id = f"spec-{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO specializations(id,name,description,policy_id,folder_node_id) VALUES(?,?,?,?,?)",
            (specialization_id, spec["name"], spec.get("description", ""), policy_id, spec_id),
        )
        for course in spec["courses"]:
            course_id = f"node-{uuid.uuid4().hex[:12]}"
            course_path = f"{spec_path}/{course['name']}"
            db.execute(
                "INSERT INTO folder_nodes(id,policy_id,name,parent_id,type,path,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (course_id, policy_id, course["name"], spec_id, "course", course_path, "active", timestamp, timestamp),
            )
            for folder in course["standard_folders"]:
                folder_id = f"node-{uuid.uuid4().hex[:12]}"
                folder_path = f"{course_path}/{folder}"
                db.execute(
                    "INSERT INTO folder_nodes(id,policy_id,name,parent_id,type,path,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (folder_id, policy_id, folder, course_id, "standard_folder", folder_path, "active", timestamp, timestamp),
                )
    audit(db, user["code"], "policy_file.activate", "policy", policy_id, {"faculty": faculty, "specializations": len(parsed["specializations"])})
    return policy_public(db.execute("SELECT * FROM policy_files WHERE id=?", (policy_id,)).fetchone())


def policy_public(row) -> dict:
    item = dict(row)
    parsed = json.loads(item["parsed_json"])
    item["parsed_json"] = normalize_policy_tree(parsed if isinstance(parsed, dict) else {})
    return item


def list_policy_files(db) -> list[dict]:
    return [policy_public(row) for row in db.execute("SELECT * FROM policy_files ORDER BY created_at DESC").fetchall()]


def delete_policy_file(db, user: dict, policy_id: str) -> dict:
    policy = db.execute("SELECT * FROM policy_files WHERE id=?", (policy_id,)).fetchone()
    if not policy:
        raise ValueError("Policy khong ton tai.")
    if policy["status"] == "active":
        raise PermissionError("Không thể xóa policy đang active. Hãy activate policy khác trước.")
    specs = rows(db.execute("SELECT id FROM specializations WHERE policy_id=?", (policy_id,)).fetchall())
    spec_ids = [item["id"] for item in specs]
    if spec_ids:
        placeholders = ",".join("?" for _ in spec_ids)
        db.execute(f"DELETE FROM lecturer_folder_nodes WHERE specialization_id IN ({placeholders})", tuple(spec_ids))
        db.execute(f"DELETE FROM lecturer_specializations WHERE specialization_id IN ({placeholders})", tuple(spec_ids))
    db.execute(
        "DELETE FROM lecturer_folder_nodes WHERE source_master_node_id IN (SELECT id FROM folder_nodes WHERE policy_id=?)",
        (policy_id,),
    )
    db.execute("DELETE FROM specializations WHERE policy_id=?", (policy_id,))
    db.execute("DELETE FROM folder_nodes WHERE policy_id=?", (policy_id,))
    db.execute("DELETE FROM policy_files WHERE id=?", (policy_id,))
    audit(db, user["code"], "policy_file.delete", "policy", policy_id, {"title": policy["title"], "status": policy["status"]})
    return {"status": "deleted", "id": policy_id}


def master_tree(db) -> dict:
    policy = active_policy(db)
    if not policy:
        return {"policy": None, "tree": None, "message": "He thong chua co policy active. Vui long lien he Admin."}
    nodes = rows(db.execute("SELECT * FROM folder_nodes WHERE policy_id=? ORDER BY path", (policy["id"],)).fetchall())
    return {"policy": policy_public(policy), "tree": build_tree_from_rows(nodes)}


def active_specializations(db) -> list[dict]:
    policy = active_policy(db)
    if not policy:
        return []
    items = rows(db.execute("SELECT * FROM specializations WHERE policy_id=? ORDER BY name", (policy["id"],)).fetchall())
    for item in items:
        item["courses_count"] = db.execute(
            "SELECT COUNT(*) count FROM folder_nodes WHERE parent_id=? AND type='course' AND status='active'",
            (item["folder_node_id"],),
        ).fetchone()["count"]
    return items


def public_specializations(db) -> list[dict]:
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "description": item.get("description", ""),
            "courses_count": item.get("courses_count", 0),
        }
        for item in active_specializations(db)
    ]


def user_specializations(db, user_code: str) -> list[dict]:
    policy = active_policy(db)
    if not policy:
        return []
    return rows(db.execute(
        """SELECT s.* FROM lecturer_specializations ls
           JOIN specializations s ON s.id=ls.specialization_id
           WHERE ls.user_code=? AND s.policy_id=? ORDER BY s.name""",
        (user_code, policy["id"]),
    ).fetchall())


def set_user_specializations(db, user: dict, specialization_ids: list[str]) -> dict:
    policy = active_policy(db)
    if not policy:
        raise ValueError("He thong chua co policy active. Vui long lien he Admin.")
    allowed = {item["id"] for item in active_specializations(db)}
    requested = set(specialization_ids)
    if not requested.issubset(allowed):
        raise ValueError("Nhom chuyen mon khong thuoc policy active.")
    db.execute(
        "DELETE FROM lecturer_specializations WHERE user_code=? AND specialization_id IN (SELECT id FROM specializations WHERE policy_id=?)",
        (user["code"], policy["id"]),
    )
    for spec_id in sorted(requested):
        db.execute(
            "INSERT OR IGNORE INTO lecturer_specializations(id,user_code,specialization_id,created_at) VALUES(?,?,?,?)",
            (f"ls-{uuid.uuid4().hex[:12]}", user["code"], spec_id, now()),
        )
    sync_lecturer_folder_nodes(db, user["code"], requested)
    audit(db, user["code"], "profile.specializations_update", "user", user["code"], {"count": len(requested)})
    return profile_specializations(db, user["code"])


def sync_lecturer_folder_nodes(db, user_code: str, specialization_ids: set[str]) -> None:
    timestamp = now()
    active_ids = set(specialization_ids)
    if active_ids:
        placeholders = ",".join("?" for _ in active_ids)
        db.execute(
            f"UPDATE lecturer_folder_nodes SET status='inactive',updated_at=? WHERE user_code=? AND specialization_id NOT IN ({placeholders})",
            (timestamp, user_code, *active_ids),
        )
    else:
        db.execute("UPDATE lecturer_folder_nodes SET status='inactive',updated_at=? WHERE user_code=?", (timestamp, user_code))

    for spec in active_specializations(db):
        if spec["id"] not in active_ids:
            continue
        master_nodes = rows(db.execute(
            "SELECT * FROM folder_nodes WHERE id IN ({}) AND status='active'".format(
                ",".join("?" for _ in subtree_node_ids(db, spec["folder_node_id"]))
            ),
            tuple(subtree_node_ids(db, spec["folder_node_id"])),
        ).fetchall())
        master_by_id = {node["id"]: node for node in master_nodes}
        pending = [spec["folder_node_id"]]
        cloned: dict[str, str] = {}
        while pending:
            source_id = pending.pop(0)
            node = master_by_id[source_id]
            parent_source_id = node.get("parent_id")
            parent_clone_id = cloned.get(parent_source_id)
            existing = db.execute(
                "SELECT * FROM lecturer_folder_nodes WHERE user_code=? AND source_master_node_id=?",
                (user_code, source_id),
            ).fetchone()
            clone_id = existing["id"] if existing else f"lfn-{uuid.uuid4().hex[:12]}"
            if existing:
                db.execute(
                    "UPDATE lecturer_folder_nodes SET parent_id=?,name=?,type=?,specialization_id=?,status='active',updated_at=? WHERE id=?",
                    (parent_clone_id, node["name"], node["type"], spec["id"], timestamp, clone_id),
                )
            else:
                db.execute(
                    """INSERT INTO lecturer_folder_nodes(id,user_code,parent_id,name,type,source_master_node_id,specialization_id,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,'active',?,?)""",
                    (clone_id, user_code, parent_clone_id, node["name"], node["type"], source_id, spec["id"], timestamp, timestamp),
                )
            cloned[source_id] = clone_id
            children = [item["id"] for item in master_nodes if item.get("parent_id") == source_id]
            pending.extend(children)


def build_lecturer_folder_tree(db, user_code: str) -> dict:
    nodes = rows(db.execute(
        "SELECT * FROM lecturer_folder_nodes WHERE user_code=? AND status='active' ORDER BY name",
        (user_code,),
    ).fetchall())
    by_parent: dict[str | None, list[dict]] = {}
    known_ids = {node["id"] for node in nodes}
    for node in nodes:
        parent_id = node.get("parent_id") if node.get("parent_id") in known_ids else None
        by_parent.setdefault(parent_id, []).append(node)
    type_order = {"specialization": 0, "course": 1, "standard_folder": 2, "folder": 2}
    for siblings in by_parent.values():
        siblings.sort(key=lambda item: (type_order.get(item["type"], 9), item["name"].lower()))

    def build(node: dict) -> dict:
        return {
            "id": node["id"],
            "name": node["name"],
            "type": "folder" if node["type"] == "standard_folder" else node["type"],
            "children": [build(child) for child in by_parent.get(node["id"], [])],
        }

    return {"id": f"root-{user_code}", "name": "Kho của tôi", "type": "root", "children": [build(node) for node in by_parent.get(None, [])]}


def profile_specializations(db, user_code: str) -> dict:
    policy = active_policy(db)
    all_specs = active_specializations(db)
    selected = user_specializations(db, user_code)
    return {
        "policy": policy_public(policy) if policy else None,
        "available": all_specs,
        "selected_ids": [item["id"] for item in selected],
        "message": None if policy else "He thong chua co policy active. Vui long lien he Admin.",
    }


def subtree_node_ids(db, root_id: str) -> set[str]:
    pending = [root_id]
    result: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in result:
            continue
        result.add(node_id)
        pending.extend(row["id"] for row in db.execute("SELECT id FROM folder_nodes WHERE parent_id=? AND status='active'", (node_id,)).fetchall())
    return result


def allowed_folder_node_ids(db, user: dict) -> set[str]:
    if user["role"] in {"admin", "head"}:
        policy = active_policy(db)
        if not policy:
            return set()
        return {row["id"] for row in db.execute("SELECT id FROM folder_nodes WHERE policy_id=? AND status='active'", (policy["id"],)).fetchall()}
    allowed: set[str] = set()
    for spec in user_specializations(db, user["code"]):
        allowed.update(subtree_node_ids(db, spec["folder_node_id"]))
    return allowed


def validate_folder_access(db, user: dict, folder_node_id: str | None) -> dict | None:
    if not folder_node_id:
        return None
    node = db.execute("SELECT * FROM folder_nodes WHERE id=? AND status='active'", (folder_node_id,)).fetchone()
    if not node:
        raise PermissionError("Thu muc trong Master Tree khong ton tai hoac da deprecated.")
    if folder_node_id not in allowed_folder_node_ids(db, user):
        raise PermissionError("Ban khong co quyen upload vao nhanh chuyen mon nay.")
    return dict(node)


def get_my_folder_tree(db, user: dict) -> dict:
    policy = active_policy(db)
    if not policy:
        return {
            "policy": None,
            "name": "Kho cua toi",
            "children": [],
            "message": "He thong chua co policy active. Vui long lien he Admin.",
        }
    specs = user_specializations(db, user["code"])
    if user["role"] in {"admin", "head"}:
        nodes = rows(db.execute("SELECT * FROM folder_nodes WHERE policy_id=? AND status='active'", (policy["id"],)).fetchall())
        return {"policy": policy_public(policy), "name": "Kho cua toi", "children": [build_tree_from_rows(nodes)]}
    if not specs:
        return {
            "policy": policy_public(policy),
            "name": "Kho cua toi",
            "children": [],
            "message": "Ban chua chon nhom chuyen mon. Vui long cap nhat ho so de he thong tao cay thu muc phu hop.",
        }
    nodes: list[dict] = []
    for spec in specs:
        ids = subtree_node_ids(db, spec["folder_node_id"])
        if not ids:
            continue
        placeholders = ",".join("?" for _ in ids)
        nodes.extend(rows(db.execute(f"SELECT * FROM folder_nodes WHERE id IN ({placeholders}) AND status='active'", tuple(ids)).fetchall()))
    return {"policy": policy_public(policy), "name": "Kho cua toi", "children": build_tree_from_rows(nodes, "Kho cua toi")["children"]}


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
    if document["owner_code"] == user["code"]:
        return True
    if document["visibility"] == "private":
        approved = db.execute(
            "SELECT 1 FROM access_requests WHERE document_id=? AND requester_code=? AND status='approved'",
            (document["id"], user["code"]),
        ).fetchone()
        return bool(approved)
    if document["visibility"] == "public":
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
            "SELECT * FROM documents WHERE deleted_at IS NULL AND status='INDEXED' AND (visibility='public' OR owner_code=?) ORDER BY updated_at DESC",
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
    db.execute("DELETE FROM document_processing_jobs WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM object_refs WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM document_v2_state WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM file_assets WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM versions WHERE document_id=?", (document["id"],))
    db.execute("DELETE FROM access_requests WHERE document_id=?", (document["id"],))
    db.execute("UPDATE upload_tasks SET document_id=NULL WHERE document_id=?", (document["id"],))
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


def safe_segment(value: str, max_length: int = 30) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value).strip(" .-") or "Khác"
    if len(cleaned) <= max_length:
        return cleaned
    suffix = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:max_length - 9].rstrip(' .-')}-{suffix}"


def safe_folder_path(value: str, max_length: int = 55) -> str:
    segments = [safe_segment(part) for part in value.replace("\\", "/").split("/") if part.strip()]
    result = "/".join(segments)
    while len(result) > max_length and segments:
        longest = max(range(len(segments)), key=lambda index: len(segments[index]))
        segments[longest] = safe_segment(segments[longest], max(12, len(segments[longest]) - 5))
        result = "/".join(segments)
    return result or "Unsorted"


def safe_filename(value: str, max_length: int = 55) -> str:
    source = Path(value).name
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", Path(source).suffix)[:10]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(source).stem).strip("._-") or "upload"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    available = max(8, max_length - len(suffix) - len(digest) - 2)
    return f"{stem[:available]}-{digest}{suffix}"


def suggest_folder(db, user: dict, metadata: dict) -> str:
    row = db.execute("SELECT value FROM policies WHERE key='storage_rules'").fetchone()
    policy = json.loads(row["value"]) if row else {}
    template = policy.get("naming", "{department}/{topic}/{doc_type}/{visibility}")
    values = {**metadata, "department": user["department"], "owner_code": user["code"]}
    result = template
    for key in ("department", "topic", "doc_type", "visibility", "owner_code", "title"):
        result = result.replace(f"{{{key}}}", safe_segment(str(values.get(key, "Khác"))))
    return safe_folder_path(result)


def quick_preview_text(filename: str, mime_type: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".xml", ".html", ".log"} or mime_type.startswith("text/"):
        for encoding in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
            try:
                return raw[:12000].decode(encoding, errors="ignore")[:6000]
            except UnicodeDecodeError:
                continue
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))
            paragraphs = [text.text for text in root.iter() if text.tag.endswith("}t") and text.text]
            return "\n".join(paragraphs[:80])[:6000]
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
            return ""
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages[:2]).strip()[:6000]
        except Exception:
            return ""
    return ""


def suggest_upload_destination(db, user: dict, filename: str, preview: str) -> dict:
    text = f"{filename} {preview}".casefold()
    best: tuple[int, dict | None, dict | None] = (0, None, None)
    policy = active_policy(db)
    if policy:
        tree = json.loads(policy["parsed_json"])
        for spec in normalize_policy_tree(tree)["specializations"]:
            spec_score = 2 if spec["name"].casefold() in text else 0
            for course in spec["courses"]:
                score = spec_score + (3 if course["name"].casefold() in text else 0)
                if score > best[0]:
                    best = (score, spec, course)
    spec, course = best[1], best[2]
    doc_type = "Tài liệu khác"
    for candidate in DOCUMENT_TYPES:
        if candidate.casefold() in text or candidate.replace(" ", "_").casefold() in text:
            doc_type = candidate
            break
    folder_path = "/".join(part for part in [
        spec["name"] if spec else "",
        course["name"] if course else "",
        doc_type,
    ] if part)
    return {
        "specialization": spec["name"] if spec else "",
        "course": course["name"] if course else "",
        "confidence": 0.95 if best[0] >= 5 else (0.65 if best[0] else 0.0),
        "document_type": doc_type,
        "folder_path": safe_folder_path(folder_path) if folder_path else "",
    }


def active_course_suggestions(db, filename: str, preview: str) -> list[dict]:
    text = f"{filename} {preview}".casefold()
    policy = active_policy(db)
    suggestions: list[dict] = []
    if not policy:
        return suggestions
    specs = rows(db.execute(
        "SELECT s.id specialization_id,s.name specialization_name,s.folder_node_id specialization_node_id "
        "FROM specializations s WHERE s.policy_id=?",
        (policy["id"],),
    ).fetchall())
    for spec in specs:
        courses = rows(db.execute(
            "SELECT * FROM folder_nodes WHERE parent_id=? AND type='course' AND status='active'",
            (spec["specialization_node_id"],),
        ).fetchall())
        spec_score = 2 if spec["specialization_name"].casefold() in text else 0
        for course in courses:
            course_score = 3 if course["name"].casefold() in text else 0
            token_hits = sum(1 for token in re.findall(r"\w+", course["name"].casefold(), re.UNICODE) if len(token) > 2 and token in text)
            score = spec_score + course_score + min(token_hits, 2)
            suggestions.append({
                "specialization_id": spec["specialization_id"],
                "specialization": spec["specialization_name"],
                "course_id": course["id"],
                "course": course["name"],
                "score": score,
            })
    suggestions.sort(key=lambda item: item["score"], reverse=True)
    top = suggestions[:3]
    total = sum(max(item["score"], 0) for item in top)
    if total <= 0 and top:
        for item in top:
            item["confidence"] = round(1 / len(top), 2)
    else:
        for item in top:
            item["confidence"] = round(max(item["score"], 0) / total, 2) if total else 0
    return top


def standard_folder_for_selection(db, course_id: str | None, document_type: str) -> dict | None:
    if not course_id:
        return None
    course = db.execute("SELECT * FROM folder_nodes WHERE id=? AND type='course' AND status='active'", (course_id,)).fetchone()
    if not course:
        return None
    mapped_folder_name = map_document_type_to_standard_folder(document_type)
    
    # 1. Try exact match with mapped folder name (case-insensitive)
    exact = db.execute(
        "SELECT * FROM folder_nodes WHERE parent_id=? AND type='standard_folder' AND status='active' AND lower(name)=lower(?)",
        (course_id, mapped_folder_name),
    ).fetchone()
    if exact:
        return dict(exact)
        
    # 2. Try match with original document type name (case-insensitive)
    exact_orig = db.execute(
        "SELECT * FROM folder_nodes WHERE parent_id=? AND type='standard_folder' AND status='active' AND lower(name)=lower(?)",
        (course_id, document_type),
    ).fetchone()
    if exact_orig:
        return dict(exact_orig)
        
    # 3. Match using the mapping function on sibling standard folder names
    siblings = db.execute(
        "SELECT * FROM folder_nodes WHERE parent_id=? AND type='standard_folder' AND status='active'",
        (course_id,),
    ).fetchall()
    for sibling in siblings:
        if map_document_type_to_standard_folder(sibling["name"]) == mapped_folder_name:
            return dict(sibling)
            
    # Fallback: create a new folder node
    timestamp = now()
    folder_id = f"node-auto-{hashlib.sha256(f'{course_id}:{mapped_folder_name}'.encode('utf-8')).hexdigest()[:12]}"
    folder_path = f"{course['path']}/{mapped_folder_name}"
    db.execute(
        "INSERT OR IGNORE INTO folder_nodes(id,policy_id,name,parent_id,type,path,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (folder_id, course["policy_id"], mapped_folder_name, course_id, "standard_folder", folder_path, "active", timestamp, timestamp),
    )
    return dict(db.execute("SELECT * FROM folder_nodes WHERE id=?", (folder_id,)).fetchone())


def folder_assignment_from_metadata(db, specialization_id: str | None, course_id: str | None, document_type: str) -> dict:
    node = standard_folder_for_selection(db, course_id, document_type)
    folder_path = ""
    folder_node_id = None
    if node:
        folder_node_id = node["id"]
        folder_path = node["path"]
    return {
        "specialization_id": specialization_id,
        "course_id": course_id,
        "document_type": document_type,
        "folder_node_id": folder_node_id,
        "folder_path": safe_folder_path(folder_path) if folder_path else "",
    }


def normalize_document_folder_assignment(db, folder_node: dict | None, payload: dict, user: dict) -> dict:
    document_type = payload.get("document_type") or payload.get("doc_type") or "Tài liệu khác"
    
    # 1. If folder_node is explicitly selected standard_folder
    if folder_node and folder_node["type"] == "standard_folder":
        return {"folder_node_id": folder_node["id"], "folder_path": folder_node["path"]}
        
    # 2. If folder_node is a course, resolve to standard folder
    if folder_node and folder_node["type"] == "course":
        assignment = folder_assignment_from_metadata(db, payload.get("specialization_id"), folder_node["id"], document_type)
        if assignment["folder_node_id"]:
            payload["course_id"] = folder_node["id"]
            return {"folder_node_id": assignment["folder_node_id"], "folder_path": assignment["folder_path"]}
        else:
            raise ValueError("Không thể tìm thấy hoặc tạo thư mục chuẩn cho học phần.")
            
    # 3. If folder_node is specialization or faculty, raise ValueError
    if folder_node and folder_node["type"] in {"specialization", "faculty"}:
        raise ValueError("Tài liệu phải nằm trong thư mục loại tài liệu của một học phần, không được gắn trực tiếp vào chuyên môn hoặc khoa.")
        
    # 4. If no folder_node but course_id is provided in payload
    if payload.get("course_id"):
        assignment = folder_assignment_from_metadata(db, payload.get("specialization_id"), payload.get("course_id"), document_type)
        if assignment["folder_node_id"]:
            return {"folder_node_id": assignment["folder_node_id"], "folder_path": assignment["folder_path"]}
        else:
            raise ValueError("Không thể tìm thấy hoặc tạo thư mục chuẩn cho học phần.")
            
    # 5. Final fallback
    folder_node_id = payload.get("folder_node_id")
    folder_path = safe_folder_path(payload.get("folder_path") or suggest_folder(db, user, payload))
    
    # Double check that we don't return a course, specialization, or faculty node
    if folder_node_id:
        db_node = db.execute("SELECT type FROM folder_nodes WHERE id = ?", (folder_node_id,)).fetchone()
        if db_node and db_node["type"] in {"course", "specialization", "faculty"}:
            raise ValueError(f"Tài liệu phải nằm trong thư mục loại tài liệu của một học phần, không được gắn trực tiếp vào {db_node['type']}.")
            
    return {"folder_node_id": folder_node_id, "folder_path": folder_path}


def enqueue_processing_jobs(db, document_id: str) -> list[dict]:
    timestamp = now()
    jobs = []
    for job_type in PROCESSING_JOB_TYPES:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO document_processing_jobs(id,document_id,job_type,status,created_at) VALUES(?,?,?,?,?)",
            (job_id, document_id, job_type, "PENDING", timestamp),
        )
        jobs.append(dict(db.execute("SELECT * FROM document_processing_jobs WHERE id=?", (job_id,)).fetchone()))
    return jobs


def complete_processing_job(db, job: dict) -> None:
    timestamp = now()
    db.execute(
        "UPDATE document_processing_jobs SET status='PROCESSING',started_at=?,error_message=NULL WHERE id=?",
        (timestamp, job["id"]),
    )
    db.execute(
        "UPDATE document_processing_jobs SET status='COMPLETED',completed_at=?,error_message=NULL WHERE id=?",
        (now(), job["id"]),
    )


def fail_processing_jobs(db, document_id: str, error: str) -> None:
    db.execute(
        "UPDATE document_processing_jobs SET status='FAILED',error_message=?,completed_at=? WHERE document_id=? AND status<>'COMPLETED'",
        (error, now(), document_id),
    )
    db.execute("UPDATE documents SET status='FAILED',updated_at=? WHERE id=?", (now(), document_id))
    set_v2_state(db, document_id, indexing_status="failed")


def run_document_processing_jobs(db, document_id: str) -> dict:
    document = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not document:
        raise ValueError("Document khong ton tai.")
    jobs = rows(db.execute("SELECT * FROM document_processing_jobs WHERE document_id=? ORDER BY created_at", (document_id,)).fetchall())
    asset = db.execute(
        "SELECT * FROM file_assets WHERE document_id=? AND version_no=? ORDER BY created_at DESC LIMIT 1",
        (document_id, document["current_version"]),
    ).fetchone()
    try:
        db.execute("UPDATE documents SET status='PROCESSING',updated_at=? WHERE id=?", (now(), document_id))
        set_v2_state(db, document_id, indexing_status="processing")
        raw = Path(asset["original_path"]).read_bytes() if asset else content_for(db, dict(document)).encode("utf-8")
        full_text = extract_text(asset["original_name"] if asset else document["title"], asset["mime_type"] if asset else "text/plain", raw)
        version = db.execute(
            "SELECT * FROM versions WHERE document_id=? AND version_no=?",
            (document_id, document["current_version"]),
        ).fetchone()
        storage_path = Path(version["storage_path"])
        storage_path.write_text(full_text, encoding="utf-8")
        digest = hash_secret(full_text)
        db.execute("UPDATE versions SET content_hash=? WHERE id=?", (digest, version["id"]))
        db.execute("UPDATE documents SET content_hash=?,updated_at=? WHERE id=?", (digest, now(), document_id))
        prompts = policy_value(db, "ai_prompts", {})
        metadata = guess_metadata(asset["original_name"] if asset else document["title"], full_text, prompts.get("metadata_instructions"))
        for job in jobs:
            complete_processing_job(db, job)
        record_object_ref(db, document_id, document["current_version"], "extracted_text", f"documents/{document_id}/versions/{document['current_version']}/content.txt", full_text.encode("utf-8"), "text/plain")
        index_document(db, document_id, document["current_version"], full_text, force_local=True)
        db.execute("UPDATE documents SET status='INDEXED',updated_at=? WHERE id=?", (now(), document_id))
        audit(db, document["owner_code"], "document.processing_completed", "document", document_id, {
            "summary": metadata.get("summary", ""),
            "keywords": metadata.get("keywords", []),
            "embedding_status": "completed",
        })
        return dict(db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())
    except Exception as exc:
        fail_processing_jobs(db, document_id, str(exc))
        raise


def create_document(db, user: dict, payload: dict, defer_processing: bool = False) -> dict:
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
    folder_node = validate_folder_access(db, user, payload.get("folder_node_id"))
    assignment = normalize_document_folder_assignment(db, dict(folder_node) if folder_node else None, payload, user)
    folder_path = assignment["folder_path"]
    folder_node_id = assignment["folder_node_id"]
    document_type = payload.get("document_type") or payload["doc_type"]
    status = "UPLOADED" if defer_processing else "PROCESSING"
    db.execute(
        "INSERT INTO documents(id,title,doc_type,topic,owner_code,visibility,current_version,content_hash,created_at,updated_at,folder_path,folder_node_id,status,specialization_id,course_id,document_type) VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)",
        (doc_id, payload["title"], payload["doc_type"], payload["topic"], user["code"], payload["visibility"], digest, timestamp, timestamp, folder_path, folder_node_id, status, payload.get("specialization_id"), payload.get("course_id"), document_type),
    )
    parent_folder_name = "None"
    if folder_node_id:
        folder_row = db.execute("SELECT name FROM folder_nodes WHERE id = ?", (folder_node_id,)).fetchone()
        if folder_row:
            parent_folder_name = folder_row["name"]
    print(f"DEBUG UPLOAD: document_id={doc_id}, document_title={payload['title']}, parent_folder_id={folder_node_id}, parent_folder_name={parent_folder_name}")
    db.execute(
        "INSERT INTO versions VALUES(?,?,?,?,?,?,?)",
        (f"ver-{uuid.uuid4().hex[:12]}", doc_id, 1, str(path), digest, user["code"], timestamp),
    )
    classification = "confidential" if "đề thi" in f"{payload['title']} {payload['doc_type']} {payload['topic']}".lower() else payload["visibility"]
    set_v2_state(db, doc_id, classification=classification, indexing_status="processing" if defer_processing else "processing")
    audit(db, user["code"], "document.create", "document", doc_id, {"title": payload["title"]})
    if not defer_processing:
        record_object_ref(db, doc_id, 1, "extracted_text", f"documents/{doc_id}/versions/1/content.txt", content.encode("utf-8"), "text/plain")
        emit_outbox(db, "document.created", doc_id, {"version_no": 1, "classification": classification})
        index_document(db, doc_id, 1, content)
        db.execute("UPDATE documents SET status='INDEXED',updated_at=? WHERE id=?", (now(), doc_id))
        sync_document(db, doc_id, path)
    return dict(db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())


def save_file_asset(db, document_id: str, version_no: int, filename: str, mime_type: str, raw: bytes, defer_processing: bool = False) -> dict:
    safe_name = safe_filename(filename)
    document = db.execute("SELECT folder_path FROM documents WHERE id=?", (document_id,)).fetchone()
    folder_path = safe_folder_path(document["folder_path"]) if document and document["folder_path"] else "Unsorted"
    folder = Path(*folder_path.split("/"))
    path = STORAGE_DIR / "repository" / folder / document_id / f"v{version_no}_{safe_name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    asset_id = f"asset-{uuid.uuid4().hex[:12]}"
    db.execute(
        "INSERT INTO file_assets VALUES(?,?,?,?,?,?,?,?)",
        (asset_id, document_id, version_no, filename, str(path), mime_type, len(raw), now()),
    )
    if not defer_processing:
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


def update_document(db, user: dict, document: dict, payload: dict, defer_processing: bool = False) -> dict:
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
    document_type = payload.get("document_type") or payload["doc_type"]
    specialization_id = payload.get("specialization_id") if "specialization_id" in payload else document.get("specialization_id")
    course_id = payload.get("course_id") if "course_id" in payload else document.get("course_id")
    folder_node = validate_folder_access(db, user, payload.get("folder_node_id") or document.get("folder_node_id"))
    assignment_payload = {**payload, "specialization_id": specialization_id, "course_id": course_id, "document_type": document_type}
    assignment = normalize_document_folder_assignment(db, dict(folder_node) if folder_node else None, assignment_payload, user)
    folder_node_id = assignment["folder_node_id"]
    folder_path = assignment["folder_path"]
    db.execute(
        "UPDATE documents SET title=?,doc_type=?,topic=?,visibility=?,current_version=?,content_hash=?,updated_at=?,folder_path=?,folder_node_id=?,status=?,specialization_id=?,course_id=?,document_type=? WHERE id=?",
        (payload["title"], payload["doc_type"], payload["topic"], payload["visibility"], version, digest, now(), folder_path, folder_node_id, "UPLOADED" if defer_processing else "PROCESSING", specialization_id, course_id, document_type, document["id"]),
    )
    classification = "confidential" if "đề thi" in f"{payload['title']} {payload['doc_type']} {payload['topic']}".lower() else payload["visibility"]
    set_v2_state(db, document["id"], classification=classification, indexing_status="processing")
    audit(db, user["code"], "document.update", "document", document["id"], {"version": version})
    if not defer_processing:
        record_object_ref(db, document["id"], version, "extracted_text", f"documents/{document['id']}/versions/{version}/content.txt", content.encode("utf-8"), "text/plain")
        emit_outbox(db, "document.version_created", document["id"], {"version_no": version})
        index_document(db, document["id"], version, content)
        db.execute("UPDATE documents SET status='INDEXED',updated_at=? WHERE id=?", (now(), document["id"]))
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


def _query_intent(question: str) -> dict:
    normalized = question.lower()
    wants_books = any(term in normalized for term in ("sách", "sach", "book", "giáo trình", "giao trinh", "tham khảo", "tham khao"))
    wants_exam = any(term in normalized for term in ("đề thi", "de thi", "đáp án", "dap an", "exam", "kiểm tra", "kiem tra"))
    ai_terms = ("ai", "trí tuệ nhân tạo", "tri tue nhan tao", "artificial intelligence", "machine learning", "học máy", "hoc may", "llm")
    wants_ai = any(term in normalized for term in ai_terms)
    return {"wants_books": wants_books, "wants_exam": wants_exam, "wants_ai": wants_ai}


def _matches_query_intent(document: dict, content: str, intent: dict) -> bool:
    searchable = f"{document['title']} {document['topic']} {document['doc_type']} {document.get('folder_path') or ''} {content}".lower()
    if intent["wants_books"]:
        book_terms = ("sách", "sach", "book", "giáo trình", "giao trinh", "tham khảo", "tham khao", "reference")
        if not any(term in searchable for term in book_terms):
            return False
        exam_terms = ("đề thi", "de thi", "đáp án", "dap an", "ngân hàng câu hỏi", "ngan hang cau hoi", "exam")
        if any(term in f"{document['title']} {document['doc_type']} {document.get('folder_path') or ''}".lower() for term in exam_terms):
            return False
    if intent["wants_ai"]:
        ai_terms = ("ai", "trí tuệ nhân tạo", "tri tue nhan tao", "artificial intelligence", "machine learning", "học máy", "hoc may", "llm", "large language model")
        if not any(term in searchable for term in ai_terms):
            return False
    if intent["wants_exam"]:
        exam_terms = ("đề thi", "de thi", "đáp án", "dap an", "ngân hàng câu hỏi", "ngan hang cau hoi", "exam", "kiểm tra", "kiem tra")
        if not any(term in searchable for term in exam_terms):
            return False
    return True


def _no_matching_documents_answer(intent: dict) -> str:
    if intent["wants_books"] and intent["wants_ai"]:
        return (
            "Mình chưa tìm thấy **sách AI** phù hợp trong những tài liệu bạn được phép xem.\n\n"
            "Mình sẽ không dùng nguồn không đúng loại, ví dụ đề thi hoặc đáp án, để trả lời cho yêu cầu tìm sách.\n\n"
            "### Bạn có cần gì thêm không?\n\n"
            "- Tìm giáo trình hoặc tài liệu tham khảo theo tên học phần\n"
            "- Tìm slide/bài giảng về AI\n"
            "- Kiểm tra lại sau khi tài liệu mới được lập chỉ mục"
        )
    return (
        "Mình chưa tìm thấy tài liệu phù hợp trong những tài liệu bạn được phép xem.\n\n"
        "### Bạn có cần gì thêm không?\n\n"
        "- Thử dùng tên học phần hoặc loại tài liệu cụ thể hơn\n"
        "- Tìm theo chủ đề gần nghĩa\n"
        "- Kiểm tra lại sau khi tài liệu mới được lập chỉ mục"
    )


def ask(db, user: dict, question: str) -> dict:
    allowed = {document["id"]: document for document in rag_documents(db, user)}
    intent = _query_intent(question)
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
        matches = vector_matches[:8]
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
    scored.sort(key=lambda item: item[0], reverse=True)
    candidates = matches or scored
    filtered = [(score, document, content) for score, document, content in candidates if _matches_query_intent(document, content, intent)]
    if filtered:
        matches = filtered[:3]
    elif intent["wants_books"] or intent["wants_exam"] or intent["wants_ai"]:
        matches = []
    else:
        matches = scored[:3]
    audit(db, user["code"], "rag.ask", "query", None, {"question": question, "matches": len(matches), "scope": "public_or_owned"})
    if not matches:
        return {
            "answer": _no_matching_documents_answer(intent),
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
        indexed_external = False if force_local else upsert_vector(
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
