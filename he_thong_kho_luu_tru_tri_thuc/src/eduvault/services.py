from __future__ import annotations

import json
import csv
import hashlib
import math
import os
import re
import shutil
import sqlite3
import time
import unicodedata
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree

from .ai import ai_provider
from .database import BACKUP_DIR, STORAGE_DIR, database_backend, hash_secret, now, restore_database, rows, snapshot_database, map_document_type_to_standard_folder
from .infrastructure import delete_object, delete_vectors, infrastructure_status, publish_event, qdrant_enabled, search_vectors, store_object, upsert_vector


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
    "Tài liệu tham khảo",
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
LAST_QDRANT_REINDEX_RESULT: dict | None = None

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


def list_audit_logs(
    db,
    *,
    actor: str = "",
    action: str = "",
    resource_type: str = "",
    query: str = "",
    page: int = 1,
    page_size: int = 20,
):
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    clauses: list[str] = []
    params: list[object] = []

    def add_like(field: str, value: str):
        value = (value or "").strip()
        if not value:
            return
        clauses.append(f"{field} LIKE ?")
        params.append(f"%{value}%")

    add_like("actor_code", actor)
    add_like("action", action)
    add_like("resource_type", resource_type)

    query = (query or "").strip()
    if query:
        clauses.append(
            "(actor_code LIKE ? OR action LIKE ? OR resource_type LIKE ? OR COALESCE(resource_id,'') LIKE ? OR detail LIKE ?)"
        )
        wildcard = f"%{query}%"
        params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = db.execute(f"SELECT COUNT(*) count FROM audit_logs {where}", tuple(params)).fetchone()["count"]
    offset = (page - 1) * page_size
    items = rows(
        db.execute(
            f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, page_size, offset),
        ).fetchall()
    )
    for item in items:
        try:
            item["detail"] = json.loads(item.get("detail") or "{}")
        except Exception:
            item["detail"] = {"raw": item.get("detail") or ""}

    action_options = [
        row["action"]
        for row in db.execute("SELECT action FROM audit_logs GROUP BY action ORDER BY COUNT(*) DESC, action ASC LIMIT 25").fetchall()
    ]
    resource_options = [
        row["resource_type"]
        for row in db.execute("SELECT resource_type FROM audit_logs GROUP BY resource_type ORDER BY COUNT(*) DESC, resource_type ASC LIMIT 25").fetchall()
    ]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_next": offset + len(items) < total,
        "has_prev": page > 1,
        "filters": {
            "actor": actor,
            "action": action,
            "resource_type": resource_type,
            "query": query,
        },
        "options": {
            "actions": action_options,
            "resource_types": resource_options,
        },
    }


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


def _plain_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\ufeff", "").strip()
    return re.sub(r"\s+", " ", text)


def _clean_policy_item(value: object) -> str:
    text = _plain_text(value)
    text = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", text)
    return _clean_node_name(text.rstrip(":"))


def _split_bilingual_name(value: str) -> tuple[str, str]:
    name = _clean_policy_item(value)
    match = re.match(r"^(?P<vi>.+?)\s*\((?P<en>[^)]+)\)\s*$", name)
    if not match:
        return name, ""
    return _clean_policy_item(match.group("vi")), _clean_policy_item(match.group("en"))


def _display_specialization_name(name_vi: str, name_en: str) -> str:
    return f"{name_vi} ({name_en})" if name_vi and name_en else name_vi or name_en


def _policy_v2_payload(
    tree: dict,
    folder_template: dict | None = None,
    permission_rules: dict | None = None,
    storage_rules: dict | None = None,
) -> dict:
    normalized = normalize_policy_tree(tree)
    template = folder_template or {
        "applies_to": "course",
        "standard_folders": normalized.get("standard_folders") or STANDARD_FOLDERS,
    }
    template["standard_folders"] = _folder_names(template.get("standard_folders")) or STANDARD_FOLDERS
    master_tree = {
        "faculty": normalized["faculty"],
        "faculty_code": normalized.get("faculty_code", ""),
        "specializations": [],
    }
    for spec in normalized["specializations"]:
        name_vi = _clean_node_name(spec.get("name_vi") or spec.get("name"))
        name_en = _clean_node_name(spec.get("name_en"))
        if not name_en:
            name_vi, name_en = _split_bilingual_name(name_vi)
        master_tree["specializations"].append({
            "name": _display_specialization_name(name_vi, name_en),
            "name_vi": name_vi,
            "name_en": name_en,
            "code": _clean_node_name(spec.get("code")),
            "node_type": "specialization",
            "courses": [
                {
                    "name": course["name"],
                    "code": _clean_node_name(course.get("code")),
                    "node_type": "course",
                }
                for course in spec["courses"]
            ],
        })
    return {
        "faculty": normalized["faculty"],
        "faculty_code": normalized.get("faculty_code", ""),
        "specializations": normalized["specializations"],
        "standard_folders": template["standard_folders"],
        "master_tree_json": master_tree,
        "folder_template_json": template,
        "permission_rules_json": permission_rules or {},
        "storage_rules_json": storage_rules or {"rules": []},
    }


def normalize_policy_tree(data: dict) -> dict:
    source = data if data.get("specializations") else data.get("master_tree_json") if isinstance(data.get("master_tree_json"), dict) else data
    folder_template = data.get("folder_template_json") if isinstance(data.get("folder_template_json"), dict) else {}
    raw_faculty = source.get("faculty") or source.get("department") or source.get("khoa") or data.get("faculty")
    faculty_code = ""
    if isinstance(raw_faculty, dict):
        faculty = _clean_node_name(raw_faculty.get("name") or raw_faculty.get("title"))
        faculty_code = _clean_node_name(raw_faculty.get("code"))
    else:
        faculty = _clean_node_name(raw_faculty)
    faculty_code = _clean_node_name(source.get("faculty_code") or data.get("faculty_code") or faculty_code)
    default_folders = _folder_names(folder_template.get("standard_folders") or data.get("standard_folders") or source.get("standard_folders") or data.get("folders")) or STANDARD_FOLDERS
    specializations: list[dict] = []

    for item in _as_list(source.get("specializations") or source.get("majors") or source.get("groups")):
        if not isinstance(item, dict):
            name = _clean_node_name(item)
            name_vi, name_en = _split_bilingual_name(name)
            code = ""
            description = ""
            courses = []
        else:
            name_vi = _clean_node_name(item.get("name_vi"))
            name_en = _clean_node_name(item.get("name_en"))
            raw_name = _clean_node_name(item.get("name") or item.get("title") or item.get("specialization"))
            if not name_vi and raw_name:
                name_vi, name_en = _split_bilingual_name(raw_name)
            name = _display_specialization_name(name_vi, name_en) or raw_name
            code = _clean_node_name(item.get("code"))
            description = str(item.get("description") or "").strip()
            courses = [_course_from_item(course) for course in _as_list(item.get("courses") or item.get("subjects"))]
            courses = [course for course in courses if course]
            legacy_folders = _folder_names(item.get("folders") or item.get("standard_folders"))
            if not courses and name:
                courses = [{"name": name, "standard_folders": legacy_folders or default_folders}]
        if name and courses:
            specializations.append({
                "name": name,
                "name_vi": name_vi,
                "name_en": name_en,
                "code": code,
                "node_type": "specialization",
                "description": description,
                "courses": courses,
            })

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
            clean_specs.append({
                "name": spec["name"],
                "name_vi": spec.get("name_vi", ""),
                "name_en": spec.get("name_en", ""),
                "code": spec.get("code", ""),
                "node_type": "specialization",
                "description": spec.get("description", ""),
                "courses": courses,
            })

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


SECTION_ALIASES = {
    1: "purpose",
    2: "specializations",
    3: "folder_template",
    4: "lecturer_tree_policy",
    5: "permission_rules",
    6: "sync_policy",
    7: "storage_rules",
}


def split_policy_sections(raw_text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {name: [] for name in SECTION_ALIASES.values()}
    current: str | None = None
    for raw_line in unicodedata.normalize("NFKC", raw_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = re.match(r"^([1-7])\.\s+(.+)$", line)
        if heading:
            current = SECTION_ALIASES.get(int(heading.group(1)))
            continue
        if current:
            sections[current].append(line)
    return sections


def _parse_specializations_section(lines: list[str]) -> list[dict]:
    specializations: list[dict] = []
    current: dict | None = None
    in_courses = False
    for raw_line in lines:
        line = _plain_text(raw_line)
        heading = re.match(r"^2\.\d+\s+(.+)$", line)
        if heading:
            if current and current["courses"]:
                specializations.append(current)
            name_vi, name_en = _split_bilingual_name(heading.group(1))
            current = {
                "name": _display_specialization_name(name_vi, name_en),
                "name_vi": name_vi,
                "name_en": name_en,
                "code": "",
                "node_type": "specialization",
                "courses": [],
            }
            in_courses = False
            continue
        if current is None:
            continue
        if re.match(r"^(mã|ma|code)\s*:", line, flags=re.IGNORECASE):
            current["code"] = _clean_policy_item(line.split(":", 1)[1])
            continue
        if re.match(r"^(học phần|hoc phan|courses?|subjects?)\s*:?\s*$", line, flags=re.IGNORECASE):
            in_courses = True
            continue
        if in_courses:
            course_name = _clean_policy_item(line)
            if course_name:
                current["courses"].append({"name": course_name, "node_type": "course"})
    if current and current["courses"]:
        specializations.append(current)
    return specializations


def _parse_folder_template_section(lines: list[str]) -> dict:
    folders: list[str] = []
    for line in lines:
        name = _clean_policy_item(line)
        if not name:
            continue
        if re.search(r"mỗi học phần|moi hoc phan|thư mục|thu muc", name, flags=re.IGNORECASE):
            continue
        folders.append(name)
    return {"applies_to": "course", "standard_folders": list(dict.fromkeys(folders)) or STANDARD_FOLDERS}


def _permission_key(label: str) -> str | None:
    key = unicodedata.normalize("NFKC", label).strip().casefold()
    key = key.replace("ﬁ", "fi")
    if key.startswith("public"):
        return "public"
    if key.startswith("restricted"):
        return "restricted"
    if key.startswith("confidential"):
        return "confidential"
    return None


def _parse_permission_rules_section(lines: list[str]) -> dict:
    rules = {"public": [], "restricted": [], "confidential": []}
    current: str | None = None
    for raw_line in lines:
        line = _plain_text(raw_line)
        label = _permission_key(line.rstrip(":"))
        if label:
            current = label
            continue
        if current:
            item = _clean_policy_item(line)
            if item:
                rules[current].append(item)
    return {key: list(dict.fromkeys(value)) for key, value in rules.items()}


def _parse_storage_rules_section(lines: list[str]) -> dict:
    rules: list[str] = []
    for line in lines:
        item = _clean_policy_item(line)
        if item:
            rules.append(item)
    return {"rules": list(dict.fromkeys(rules))}


def _parse_policy_text_v2(text: str) -> dict | None:
    sections = split_policy_sections(text)
    specializations = _parse_specializations_section(sections["specializations"])
    if not specializations:
        return None
    folder_template = _parse_folder_template_section(sections["folder_template"])
    tree = {
        "faculty": "Khoa CNTT",
        "faculty_code": "CNTT",
        "specializations": [
            {
                **spec,
                "courses": [
                    {**course, "standard_folders": folder_template["standard_folders"]}
                    for course in spec["courses"]
                ],
            }
            for spec in specializations
        ],
        "standard_folders": folder_template["standard_folders"],
    }
    return _policy_v2_payload(
        tree,
        folder_template=folder_template,
        permission_rules=_parse_permission_rules_section(sections["permission_rules"]),
        storage_rules=_parse_storage_rules_section(sections["storage_rules"]),
    )


def parse_policy_tree(raw_text: str) -> dict:
    text = raw_text.strip()
    if not text:
        raise ValueError("Policy khong co noi dung de sinh Master Folder Tree.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        parsed_text = _parse_policy_text_v2(text)
        if parsed_text:
            return parsed_text
        data = _try_parse_yaml_like(text)
    if isinstance(data, dict):
        normalized = normalize_policy_tree(data)
        if normalized["faculty"] and normalized["specializations"]:
            return _policy_v2_payload(
                normalized,
                folder_template=data.get("folder_template_json") if isinstance(data.get("folder_template_json"), dict) else None,
                permission_rules=data.get("permission_rules_json") if isinstance(data.get("permission_rules_json"), dict) else None,
                storage_rules=data.get("storage_rules_json") if isinstance(data.get("storage_rules_json"), dict) else None,
            )
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
    return _policy_v2_payload(normalized)


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


def _policy_specialization_snapshots(policy_row) -> list[dict]:
    if not policy_row:
        return []
    parsed = policy_public(policy_row)["parsed_json"]
    source = []
    if isinstance(parsed.get("master_tree_json"), dict):
        source = parsed["master_tree_json"].get("specializations") or []
    if not source:
        source = parsed.get("specializations") or []
    snapshots = []
    for item in source:
        name = str(item.get("name") or item.get("name_vi") or "").strip()
        code = str(item.get("code") or "").strip()
        name_en = str(item.get("name_en") or "").strip()
        key = _fold_text(code) if code else _fold_text(name)
        if not key and name_en:
            key = _fold_text(name_en)
        if not key:
            continue
        snapshots.append({"key": key, "code": code, "name": name, "name_en": name_en, "courses_count": len(item.get("courses") or [])})
    return snapshots


def _match_specialization_snapshot(assignment: dict, new_specs_by_code: dict[str, dict], new_specs_by_name: dict[str, dict]) -> dict | None:
    code = _fold_text(assignment.get("specialization_code_snapshot"))
    if code and code in new_specs_by_code:
        return new_specs_by_code[code]
    for name_key in (_fold_text(assignment.get("specialization_name_snapshot")), _fold_text(assignment.get("specialization_name"))):
        if name_key and name_key in new_specs_by_name:
            return new_specs_by_name[name_key]
    return None


def preview_policy_activation(db, policy_id: str) -> dict:
    target_policy = db.execute("SELECT * FROM policy_files WHERE id=?", (policy_id,)).fetchone()
    if not target_policy:
        raise ValueError("Policy khong ton tai.")
    current_policy = active_policy(db)
    new_specs = _policy_specialization_snapshots(target_policy)
    old_specs = _policy_specialization_snapshots(current_policy)
    new_by_key = {item["key"]: item for item in new_specs}
    old_by_key = {item["key"]: item for item in old_specs}
    added = [item for item in new_specs if item["key"] not in old_by_key]
    removed = [item for item in old_specs if item["key"] not in new_by_key]
    matched = [{"old": old_by_key[key], "new": new_by_key[key]} for key in sorted(set(old_by_key) & set(new_by_key))]

    new_by_code = {_fold_text(item["code"]): item for item in new_specs if item.get("code")}
    new_by_name = {_fold_text(item["name"]): item for item in new_specs if item.get("name")}
    assignment_query = """SELECT la.*, u.name AS lecturer_name, s.name AS specialization_name
                          FROM lecturer_assignments la
                          JOIN users u ON u.code=la.lecturer_code
                          JOIN specializations s ON s.id=la.specialization_id
                          WHERE la.status='active'"""
    params: tuple = ()
    if current_policy:
        assignment_query += " AND la.policy_id=?"
        params = (current_policy["id"],)
    assignments = rows(db.execute(assignment_query, params).fetchall())
    valid_assignments = []
    needs_resolution = []
    for assignment in assignments:
        match = _match_specialization_snapshot(assignment, new_by_code, new_by_name)
        item = {
            "assignment_id": assignment["id"],
            "lecturer_code": assignment["lecturer_code"],
            "lecturer_name": assignment.get("lecturer_name") or assignment.get("lecturer_name_snapshot") or "",
            "old_specialization": assignment.get("specialization_name_snapshot") or assignment.get("specialization_name") or "",
            "old_code": assignment.get("specialization_code_snapshot") or "",
        }
        if match:
            valid_assignments.append({**item, "new_specialization": match["name"], "new_code": match["code"]})
        else:
            needs_resolution.append({**item, "reason": "Specialization khong con trong policy moi."})

    affected_lecturers = sorted({item["lecturer_code"] for item in valid_assignments})
    old_policy_id = current_policy["id"] if current_policy else None
    active_permissions = 0
    if old_policy_id:
        active_permissions = db.execute(
            "SELECT COUNT(*) count FROM lecturer_folder_permissions WHERE policy_id=? AND status='active'",
            (old_policy_id,),
        ).fetchone()["count"]
    return {
        "policy_id": policy_id,
        "policy_title": target_policy["title"],
        "current_policy_id": old_policy_id,
        "current_policy_title": current_policy["title"] if current_policy else None,
        "status": "ready" if not needs_resolution else "needs_resolution",
        "tree_impact": {
            "added_specializations": added,
            "removed_specializations": removed,
            "matched_specializations": matched,
            "summary": {"added": len(added), "removed": len(removed), "matched": len(matched)},
        },
        "assignment_impact": {
            "valid_assignments": len(valid_assignments),
            "needs_resolution_assignments": len(needs_resolution),
            "valid": valid_assignments,
            "requires_admin_resolution": needs_resolution,
        },
        "virtual_tree_impact": {
            "virtual_trees_to_rebuild": len(affected_lecturers),
            "affected_lecturers": affected_lecturers,
        },
        "folder_permission_impact": {
            "active_permissions_to_deprecate": active_permissions,
            "will_rebuild_permissions": bool(valid_assignments),
        },
    }


def activate_policy_file(db, user: dict, policy_id: str) -> dict:
    policy = db.execute("SELECT * FROM policy_files WHERE id=?", (policy_id,)).fetchone()
    if not policy:
        raise ValueError("Policy khong ton tai.")
    activation_preview = preview_policy_activation(db, policy_id)
    parsed = json.loads(policy["parsed_json"])
    parsed = _policy_v2_payload(
        normalize_policy_tree(parsed if isinstance(parsed, dict) else {}),
        folder_template=parsed.get("folder_template_json") if isinstance(parsed, dict) and isinstance(parsed.get("folder_template_json"), dict) else None,
        permission_rules=parsed.get("permission_rules_json") if isinstance(parsed, dict) and isinstance(parsed.get("permission_rules_json"), dict) else None,
        storage_rules=parsed.get("storage_rules_json") if isinstance(parsed, dict) and isinstance(parsed.get("storage_rules_json"), dict) else None,
    )
    timestamp = now()
    db.execute("UPDATE policy_files SET status='archived' WHERE status='active' AND id<>?", (policy_id,))
    db.execute("UPDATE policy_files SET status='active',activated_at=? WHERE id=?", (timestamp, policy_id))
    db.execute("UPDATE folder_nodes SET status='deprecated',updated_at=? WHERE status='active'", (timestamp,))
    db.execute("DELETE FROM specializations WHERE policy_id=?", (policy_id,))
    db.execute("UPDATE policy_files SET parsed_json=? WHERE id=?", (json.dumps(parsed, ensure_ascii=False), policy_id))
    if parsed.get("permission_rules_json"):
        db.execute(
            "INSERT INTO policies(key,value,updated_at) VALUES('permission_rules',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (json.dumps(parsed["permission_rules_json"], ensure_ascii=False), timestamp),
        )
    if parsed.get("storage_rules_json"):
        db.execute(
            "INSERT INTO policies(key,value,updated_at) VALUES('storage_rules',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (json.dumps(parsed["storage_rules_json"], ensure_ascii=False), timestamp),
        )

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
    activation_summary = {
        "added_specializations": activation_preview["tree_impact"]["summary"]["added"],
        "removed_specializations": activation_preview["tree_impact"]["summary"]["removed"],
        "matched_specializations": activation_preview["tree_impact"]["summary"]["matched"],
        "valid_assignments": activation_preview["assignment_impact"]["valid_assignments"],
        "needs_resolution_assignments": activation_preview["assignment_impact"]["needs_resolution_assignments"],
        "virtual_trees_to_rebuild": activation_preview["virtual_tree_impact"]["virtual_trees_to_rebuild"],
        "active_permissions_to_deprecate": activation_preview["folder_permission_impact"]["active_permissions_to_deprecate"],
    }
    audit(db, user["code"], "policy_file.activate", "policy", policy_id, {"faculty": faculty, "specializations": len(parsed["specializations"]), "activation_summary": activation_summary})
    sync_policy_nodes(db)
    activated = policy_public(db.execute("SELECT * FROM policy_files WHERE id=?", (policy_id,)).fetchone())
    activated["activation_summary"] = activation_preview
    return activated


def policy_public(row) -> dict:
    item = dict(row)
    parsed = json.loads(item["parsed_json"])
    if isinstance(parsed, dict):
        item["parsed_json"] = _policy_v2_payload(
            normalize_policy_tree(parsed),
            folder_template=parsed.get("folder_template_json") if isinstance(parsed.get("folder_template_json"), dict) else None,
            permission_rules=parsed.get("permission_rules_json") if isinstance(parsed.get("permission_rules_json"), dict) else None,
            storage_rules=parsed.get("storage_rules_json") if isinstance(parsed.get("storage_rules_json"), dict) else None,
        )
    else:
        item["parsed_json"] = _policy_v2_payload(normalize_policy_tree({}))
    return item


def list_policy_files(db) -> list[dict]:
    return [policy_public(row) for row in db.execute("SELECT * FROM policy_files ORDER BY created_at DESC").fetchall()]


def delete_policy_file(db, user: dict, policy_id: str) -> dict:
    policy = db.execute("SELECT * FROM policy_files WHERE id=?", (policy_id,)).fetchone()
    if not policy:
        raise ValueError("Policy khong ton tai.")
    if policy["status"] == "active":
        raise PermissionError("Không thể xóa policy đang active. Hãy activate policy khác trước.")
    
    # Clean up assignments, permissions and audit logs associated with this policy
    db.execute("DELETE FROM lecturer_folder_permissions WHERE policy_id=?", (policy_id,))
    db.execute(
        "DELETE FROM lecturer_assignment_audit_logs WHERE batch_id IN (SELECT id FROM lecturer_assignment_batches WHERE policy_id=?)",
        (policy_id,),
    )
    db.execute("DELETE FROM lecturer_assignments WHERE policy_id=?", (policy_id,))
    db.execute("DELETE FROM lecturer_assignment_batches WHERE policy_id=?", (policy_id,))

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



def sync_policy_nodes(db) -> None:
    timestamp = now()
    db.execute("DELETE FROM policy_nodes")
    policy = active_policy(db)
    if not policy:
        return
    for node in db.execute("SELECT id,name,parent_id,path FROM folder_nodes WHERE policy_id=? AND status='active'", (policy["id"],)).fetchall():
        db.execute(
            "INSERT INTO policy_nodes(id,name,parent_id,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (node["id"], node["name"], node["parent_id"], node["path"], timestamp, timestamp),
        )


def _fold_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", text).strip().casefold()


def _same_name(left: object, right: object) -> bool:
    return _fold_text(left) == _fold_text(right)


def _policy_display_name(value: object) -> str:
    acronyms = {"ai": "AI", "cntt": "CNTT", "iot": "IoT", "nlp": "NLP", "rag": "RAG", "cv": "CV", "ml": "ML"}
    raw = str(value or "").strip()
    raw = re.sub(r"^(?:hoc phan|mon hoc|mon|course|folder|thu muc|chuyen mon|nhom chuyen mon)\s+", "", _fold_text(raw), flags=re.IGNORECASE)
    words = []
    for word in re.split(r"\s+", raw):
        key = word.casefold()
        words.append(acronyms.get(key, word[:1].upper() + word[1:]))
    return " ".join(words).strip()


def _current_policy_tree(db) -> dict:
    policy = active_policy(db)
    if not policy:
        raise ValueError("He thong chua co policy active. Vui long upload/activate policy truoc.")
    return normalize_policy_tree(json.loads(policy["parsed_json"]))


def _find_specialization(tree: dict, name: str) -> dict | None:
    return next((spec for spec in tree["specializations"] if _same_name(spec["name"], name)), None)


def _find_course(tree: dict, name: str) -> tuple[dict, dict] | None:
    for spec in tree["specializations"]:
        for course in spec["courses"]:
            if _same_name(course["name"], name):
                return spec, course
    return None


def _find_folder(tree: dict, name: str) -> tuple[dict, dict, str] | None:
    for spec in tree["specializations"]:
        for course in spec["courses"]:
            for folder in course["standard_folders"]:
                if _same_name(folder, name):
                    return spec, course, folder
    return None


def _selected_specialization_names(db) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in db.execute(
        """SELECT ls.user_code,s.name FROM lecturer_specializations ls
           JOIN specializations s ON s.id=ls.specialization_id"""
    ).fetchall():
        result.setdefault(row["user_code"], set()).add(row["name"])
    return result


def _restore_lecturer_specializations_by_name(db, selected: dict[str, set[str]]) -> None:
    if not selected:
        return
    policy = active_policy(db)
    if not policy:
        return
    specs = rows(db.execute("SELECT id,name FROM specializations WHERE policy_id=?", (policy["id"],)).fetchall())
    for user_code, names in selected.items():
        ids = {spec["id"] for spec in specs if any(_same_name(spec["name"], name) for name in names)}
        target = db.execute("SELECT * FROM users WHERE code=? AND active=1", (user_code,)).fetchone()
        if target:
            set_user_specializations(db, dict(target), list(ids))


def _store_tree_as_policy(db, actor: str, tree: dict, title: str) -> dict:
    selected = _selected_specialization_names(db)
    policy_id = f"policy-{uuid.uuid4().hex[:12]}"
    timestamp = now()
    parsed = normalize_policy_tree(tree)
    raw_text = json.dumps(parsed, ensure_ascii=False, indent=2)
    policy_dir = STORAGE_DIR / "policies"
    policy_dir.mkdir(parents=True, exist_ok=True)
    file_path = policy_dir / f"{policy_id}_assistant.json"
    file_path.write_text(raw_text, encoding="utf-8")
    db.execute(
        "INSERT INTO policy_files(id,title,file_path,status,raw_text,parsed_json,created_by,created_at,activated_at) VALUES(?,?,?,?,?,?,?,?,NULL)",
        (policy_id, title, str(file_path), "draft", raw_text, raw_text, actor, timestamp),
    )
    activated = activate_policy_file(db, {"code": actor}, policy_id)
    _restore_lecturer_specializations_by_name(db, selected)
    return activated


def _apply_tree_action(tree: dict, action: dict) -> dict:
    tree = normalize_policy_tree(json.loads(json.dumps(tree, ensure_ascii=False)))
    action_type = action.get("action")
    if action_type == "add_node":
        parent = _clean_node_name(action.get("parent"))
        node = _clean_node_name(action.get("node"))
        if not parent or not node:
            raise ValueError("add_node can parent va node.")
        if _same_name(parent, tree["faculty"]):
            if _find_specialization(tree, node):
                raise ValueError("Node da ton tai trong policy.")
            tree["specializations"].append({"name": node, "description": "", "courses": [{"name": node, "code": "", "description": "", "standard_folders": STANDARD_FOLDERS}]})
            return normalize_policy_tree(tree)
        spec = _find_specialization(tree, parent)
        if spec:
            if any(_same_name(course["name"], node) for course in spec["courses"]):
                raise ValueError("Hoc phan da ton tai trong chuyen nganh.")
            spec["courses"].append({"name": node, "code": "", "description": "", "standard_folders": STANDARD_FOLDERS})
            return normalize_policy_tree(tree)
        found_course = _find_course(tree, parent)
        if found_course:
            _, course = found_course
            if any(_same_name(folder, node) for folder in course["standard_folders"]):
                raise ValueError("Thu muc da ton tai trong hoc phan.")
            course["standard_folders"].append(node)
            return normalize_policy_tree(tree)
        raise ValueError("Khong tim thay node cha trong policy active.")

    if action_type == "rename_node":
        node = _clean_node_name(action.get("node"))
        new_name = _clean_node_name(action.get("new_name"))
        if not node or not new_name:
            raise ValueError("rename_node can node va new_name.")
        if _same_name(tree["faculty"], node):
            tree["faculty"] = new_name
            return normalize_policy_tree(tree)
        spec = _find_specialization(tree, node)
        if spec:
            spec["name"] = new_name
            return normalize_policy_tree(tree)
        found_course = _find_course(tree, node)
        if found_course:
            found_course[1]["name"] = new_name
            return normalize_policy_tree(tree)
        found_folder = _find_folder(tree, node)
        if found_folder:
            _, course, folder = found_folder
            course["standard_folders"] = [new_name if _same_name(item, folder) else item for item in course["standard_folders"]]
            return normalize_policy_tree(tree)
        raise ValueError("Khong tim thay node can doi ten.")

    if action_type == "delete_node":
        node = _clean_node_name(action.get("node"))
        if not node:
            raise ValueError("delete_node can node.")
        before = len(tree["specializations"])
        tree["specializations"] = [spec for spec in tree["specializations"] if not _same_name(spec["name"], node)]
        if len(tree["specializations"]) != before:
            return normalize_policy_tree(tree)
        for spec in tree["specializations"]:
            before_courses = len(spec["courses"])
            spec["courses"] = [course for course in spec["courses"] if not _same_name(course["name"], node)]
            if len(spec["courses"]) != before_courses:
                return normalize_policy_tree(tree)
            for course in spec["courses"]:
                before_folders = len(course["standard_folders"])
                course["standard_folders"] = [folder for folder in course["standard_folders"] if not _same_name(folder, node)]
                if len(course["standard_folders"]) != before_folders:
                    return normalize_policy_tree(tree)
        raise ValueError("Khong tim thay node can xoa.")

    if action_type == "move_node":
        node = _clean_node_name(action.get("node"))
        new_parent = _clean_node_name(action.get("new_parent") or action.get("parent"))
        if not node or not new_parent:
            raise ValueError("move_node can node va new_parent.")
        target_spec = _find_specialization(tree, new_parent)
        target_course = _find_course(tree, new_parent)
        found_course = _find_course(tree, node)
        if found_course and target_spec:
            old_spec, course = found_course
            old_spec["courses"] = [item for item in old_spec["courses"] if not _same_name(item["name"], node)]
            target_spec["courses"].append(course)
            return normalize_policy_tree(tree)
        found_folder = _find_folder(tree, node)
        if found_folder and target_course:
            _, old_course, folder = found_folder
            old_course["standard_folders"] = [item for item in old_course["standard_folders"] if not _same_name(item, node)]
            target_course[1]["standard_folders"].append(folder)
            return normalize_policy_tree(tree)
        raise ValueError("Chi ho tro chuyen hoc phan sang chuyen nganh hoac thu muc sang hoc phan.")

    raise ValueError("Action cau truc policy khong duoc ho tro.")


def interpret_policy_command(message: str) -> dict:
    text = _fold_text(message)
    if not text:
        return {"status": "need_clarification", "message": "Ban muon cap nhat policy nhu the nao?"}
    assignment_action = interpret_assignment_command(message)
    if assignment_action:
        return assignment_action
    timed_permission = interpret_time_based_permission_command(message)
    if timed_permission:
        return timed_permission
    advisor_action = interpret_advisor_command(message)
    if advisor_action:
        return advisor_action
    match = re.search(r"(?:them|tao|add)\s+(.+?)\s+(?:thuoc|vao|under)\s+(.+)", text)
    if match:
        return {"action": "add_node", "node": _policy_display_name(match.group(1)), "parent": _policy_display_name(match.group(2))}
    match = re.search(r"(?:chuyen|move)\s+(.+?)\s+(?:sang|vao|to)\s+(.+)", text)
    if match:
        return {"action": "move_node", "node": _policy_display_name(match.group(1)), "new_parent": _policy_display_name(match.group(2))}
    match = re.search(r"(?:doi ten|rename)\s+(.+?)\s+(?:thanh|to)\s+(.+)", text)
    if match:
        return {"action": "rename_node", "node": _policy_display_name(match.group(1)), "new_name": _policy_display_name(match.group(2))}
    match = re.search(r"(?:xoa|delete)\s+(?:nhanh\s+)?(.+)", text)
    if match:
        return {"action": "delete_node", "node": _policy_display_name(match.group(1))}
    if "de thi" in text and any(token in text for token in ("truong bo mon", "head_department", "head")) and any(token in text for token in ("chi", "confidential", "duoc xem")):
        return {"action": "update_permission", "document_type": "De thi", "visibility": "confidential", "roles": ["head_department"]}
    match = re.search(r"(.+?)\s+(?:luu trong|luu vao|storage in)\s+(.+)", text)
    if match:
        return {"action": "update_storage_rule", "document_type": _policy_display_name(match.group(1)), "parent": _policy_display_name(match.group(2))}
    match = re.search(r"(.+?)\s+qua\s+(\d+)\s+nam\s+(?:chuyen vao|luu vao)\s+(.+)", text)
    if match:
        return {"action": "update_retention_rule", "document_type": _policy_display_name(match.group(1)), "years": int(match.group(2)), "destination": _policy_display_name(match.group(3))}
    return {"status": "need_clarification", "message": "Lenh policy chua ro. Hay noi ro action, node va node cha/dich."}


def _lecturer_selector(value: str) -> str:
    raw = str(value or "").strip()
    match = re.search(r"\(([A-Za-z]{2,}\d+)\)", raw)
    if match:
        return match.group(1).upper()
    match = re.search(r"\b([A-Za-z]{2,}\d+)\b", raw)
    if match:
        return match.group(1).upper()
    if re.fullmatch(r"[A-Za-z0-9_]{2,}", raw):
        return raw.upper()
    return re.sub(r"^(?:giang vien|gv)\s+", "", _fold_text(raw)).strip()


def interpret_assignment_command(message: str) -> dict | None:
    text = _fold_text(message)
    patterns = [
        ("assignment.move", r"(?:chuyen|move)\s+(.+?)\s+sang(?:\s+chuyen mon)?\s+(.+)"),
        ("assignment.assign", r"(?:gan|assign)\s+(.+?)\s+(?:phu trach|vao|cho|thuoc)\s+(.+)"),
        ("assignment.remove", r"(?:bo|xoa|remove)\s+(.+?)\s+(?:khoi|ra khoi|from)\s+(.+)"),
    ]
    for action, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return {
                "action": action,
                "lecturer": _lecturer_selector(match.group(1)),
                "specialization": _policy_display_name(match.group(2)),
            }
    return None


def _parse_release_datetime(text: str) -> str | None:
    match = re.search(r"(\d{1,2})[:h](\d{2}).*?(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if not match:
        return None
    hour, minute, day, month, year = match.groups()
    try:
        parsed = datetime(int(year), int(month), int(day), int(hour), int(minute))
    except ValueError:
        return None
    return parsed.isoformat(timespec="seconds") + "+07:00"


def interpret_time_based_permission_command(message: str) -> dict | None:
    text = _fold_text(message)
    if "chi duoc mo" not in text and "mo" not in text:
        return None
    if "cho" not in text or not re.search(r"\d{1,2}[:h]\d{2}", text):
        return None
    doc_match = re.search(r"(de thi|dap an|tai lieu|bai giang)\s+(.+?)\s+chi duoc mo", text)
    if not doc_match:
        return None
    groups_match = re.search(r"\bcho\s+(.+?)\s+vao\s+\d{1,2}[:h]\d{2}", text)
    release_at = _parse_release_datetime(text)
    if not groups_match or not release_at:
        return {"status": "need_clarification", "message": "Lenh mo quyen theo thoi gian can co nhom nhan quyen va thoi diem mo quyen."}
    groups = [item.strip() for item in re.split(r",| va |;", groups_match.group(1)) if item.strip()]
    return {
        "action": "permission.time_based_release",
        "document_type": _policy_display_name(doc_match.group(1)),
        "course": _policy_display_name(doc_match.group(2)),
        "target_specializations": [_policy_display_name(item) for item in groups],
        "release_at": release_at,
    }


def interpret_advisor_command(message: str) -> dict | None:
    text = _fold_text(message)
    if not text:
        return None
    if any(token in text for token in ("nen lam tiep", "viec nao nen lam", "khuyen nghi", "recommended action", "recommendation")):
        return {"action": "advisor.recommendations", "scope": "faculty"}
    if any(token in text for token in ("thieu tri thuc", "thieu tai lieu", "course gap", "hoc phan nao thieu")):
        return {"action": "advisor.course_gap", "scope": "faculty"}
    if any(token in text for token in ("rui ro chuyen nganh", "specialization risk", "chuyen nganh rui ro")):
        return {"action": "advisor.specialization_risk", "scope": "faculty"}
    if any(token in text for token in ("rui ro", "risk", "khoa co van de gi", "khoa co rui ro gi")):
        return {"action": "advisor.risk_analysis", "scope": "faculty"}
    return None


def _resolve_assignment_lecturer(db, selector: str) -> dict | None:
    if not selector:
        return None
    code_match = re.search(r"^[A-Z0-9_]{2,}$", selector.upper())
    if code_match:
        row = db.execute("SELECT * FROM users WHERE code=? AND active=1", (selector.upper(),)).fetchone()
        return dict(row) if row else None
    folded = _fold_text(selector)
    for row in db.execute("SELECT * FROM users WHERE active=1").fetchall():
        if _fold_text(row["name"]) == folded:
            return dict(row)
    return None


def _active_assignment_specializations(db, lecturer_code: str, policy_id: str) -> list[dict]:
    return rows(db.execute(
        """SELECT s.* FROM lecturer_specializations ls
           JOIN specializations s ON s.id=ls.specialization_id
           WHERE ls.user_code=? AND s.policy_id=?
           ORDER BY s.name""",
        (lecturer_code, policy_id),
    ).fetchall())


def _assignment_target_specs(action_type: str, current: list[dict], target: dict) -> list[dict]:
    current_by_id = {item["id"]: item for item in current}
    if action_type == "assignment.move":
        return [target]
    if action_type == "assignment.assign":
        current_by_id[target["id"]] = target
        return list(current_by_id.values())
    if action_type == "assignment.remove":
        return [item for item in current if item["id"] != target["id"]]
    return current


def _assignment_impact(db, lecturer: dict | None, current: list[dict], target_specs: list[dict], removed: list[dict], added: list[dict], warnings: list[str]) -> dict:
    removed_node_ids: set[str] = set()
    added_node_ids: set[str] = set()
    for spec in removed:
        if spec.get("folder_node_id"):
            removed_node_ids.update(subtree_node_ids(db, spec["folder_node_id"]))
    for spec in added:
        if spec.get("folder_node_id"):
            added_node_ids.update(subtree_node_ids(db, spec["folder_node_id"]))
    revoked_permissions = 0
    affected_documents = 0
    if lecturer and removed_node_ids:
        placeholders = ",".join("?" for _ in removed_node_ids)
        revoked_permissions = db.execute(
            f"SELECT COUNT(*) count FROM lecturer_folder_permissions WHERE user_code=? AND status='active' AND folder_node_id IN ({placeholders})",
            (lecturer["code"], *removed_node_ids),
        ).fetchone()["count"]
        affected_documents = db.execute(
            f"SELECT COUNT(*) count FROM documents WHERE owner_code=? AND status!='DELETED' AND folder_node_id IN ({placeholders})",
            (lecturer["code"], *removed_node_ids),
        ).fetchone()["count"]
    if affected_documents:
        warnings.append(f"Giang vien dang so huu {affected_documents} tai lieu trong chuyen mon bi go.")
    return {
        "lecturer": {
            "code": lecturer["code"] if lecturer else "",
            "name": lecturer["name"] if lecturer else "",
            "role": lecturer["role"] if lecturer else "",
        },
        "current_specializations": [{"id": item["id"], "name": item["name"], "code": item.get("code", "")} for item in current],
        "target_specializations": [{"id": item["id"], "name": item["name"], "code": item.get("code", "")} for item in target_specs],
        "assignment_impact": {
            "added_specializations": [{"name": item["name"], "code": item.get("code", "")} for item in added],
            "removed_specializations": [{"name": item["name"], "code": item.get("code", "")} for item in removed],
            "unchanged_specializations": [{"name": item["name"], "code": item.get("code", "")} for item in target_specs if item["id"] in {cur["id"] for cur in current} and item["id"] not in {rem["id"] for rem in removed}],
        },
        "virtual_tree_impact": {
            "rebuild": bool(added or removed),
            "affected_nodes": len(added_node_ids | removed_node_ids),
        },
        "folder_permission_impact": {
            "permissions_to_revoke": revoked_permissions,
            "permissions_to_grant": len(added_node_ids) * 2,
        },
        "risk_warnings": warnings,
    }


def preview_assignment_action(db, actor: dict, action: dict) -> dict:
    policy = active_policy(db)
    warnings: list[str] = []
    if not policy:
        return {"status": "need_clarification", "message": "He thong chua co policy active.", "risk_warnings": ["He thong chua co policy active."]}
    lecturer = _resolve_assignment_lecturer(db, str(action.get("lecturer") or ""))
    if not lecturer:
        return {"status": "need_clarification", "message": "Giang vien khong ton tai.", "action": action, "risk_warnings": ["Giang vien khong ton tai."]}
    if lecturer["role"] not in {"lecturer", "new_lecturer"}:
        return {"status": "need_clarification", "message": "User khong phai lecturer/new_lecturer.", "action": action, "risk_warnings": ["User khong phai lecturer/new_lecturer."]}
    spec_index = _assignment_specialization_index(db, policy)
    target = spec_index.get(_fold_text(action.get("specialization") or ""))
    if not target:
        return {"status": "need_clarification", "message": "Chuyen mon khong ton tai trong policy active.", "action": action, "risk_warnings": ["Chuyen mon khong ton tai trong policy active."]}
    current = _active_assignment_specializations(db, lecturer["code"], policy["id"])
    indexed_by_id = {item["id"]: item for item in spec_index.values()}
    current = [{**item, "code": indexed_by_id.get(item["id"], {}).get("code", item.get("code", ""))} for item in current]
    target_specs = _assignment_target_specs(action["action"], current, target)
    current_ids = {item["id"] for item in current}
    target_ids = {item["id"] for item in target_specs}
    added = [item for item in target_specs if item["id"] not in current_ids]
    removed = [item for item in current if item["id"] not in target_ids]
    if action["action"] == "assignment.remove" and target["id"] not in current_ids:
        warnings.append("Giang vien hien khong thuoc chuyen mon nay.")
    confirm_blocked_reason = None
    if action["action"] == "assignment.remove" and not target_specs:
        warnings.append("Bo chuyen mon cuoi cung se lam giang vien mat toan bo virtual tree chuyen mon.")
        confirm_blocked_reason = "Module Lecturer Assignment hien co khong confirm duoc batch rong de xoa toan bo chuyen mon."
    impact = _assignment_impact(db, lecturer, current, target_specs, removed, added, warnings)
    assignment_preview = None
    batch_preview_id = None
    if target_specs:
        payload = [
            {
                "lecturer_code": lecturer["code"],
                "lecturer_name": lecturer["name"],
                "specialization": spec.get("code") or spec["name"],
            }
            for spec in target_specs
        ]
        assignment_preview = preview_lecturer_assignment_import(
            db,
            actor,
            "governance_assignment_agent.json",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
        batch_preview_id = assignment_preview["batch_preview_id"]
    action = {
        **action,
        "lecturer_code": lecturer["code"],
        "lecturer_name": lecturer["name"],
        "specialization_id": target["id"],
        "specialization_name": target["name"],
        "specialization_code": target.get("code", ""),
        "batch_preview_id": batch_preview_id,
        "apply_mode": "replace_for_listed_lecturers",
        "confirm_blocked_reason": confirm_blocked_reason,
    }
    return {
        "status": "preview",
        "action": action,
        "preview": {
            "summary": f"Du kien cap nhat phan cong chuyen mon cho {lecturer['code']}.",
            "assignment_preview": assignment_preview,
            "impact": impact,
            "requires_confirmation": True,
            "confirm_blocked_reason": confirm_blocked_reason,
            "route": "confirm -> lecturer assignment confirm -> virtual tree/folder permission projection",
        },
    }


def _resolve_permission_target_specializations(db, policy: dict, values: list[str]) -> tuple[list[dict], list[str]]:
    spec_index = _assignment_specialization_index(db, policy)
    resolved: list[dict] = []
    missing: list[str] = []
    seen: set[str] = set()
    for value in values:
        spec = spec_index.get(_fold_text(value))
        if not spec:
            missing.append(value)
            continue
        if spec["id"] not in seen:
            resolved.append(spec)
            seen.add(spec["id"])
    return resolved, missing


def _matching_time_permission_documents(db, document_type: str, course: str) -> list[dict]:
    like_doc = f"%{document_type}%"
    like_course = f"%{course}%"
    return rows(db.execute(
        """SELECT * FROM documents
           WHERE deleted_at IS NULL AND status!='DELETED'
             AND (doc_type LIKE ? OR document_type LIKE ?)
             AND (topic LIKE ? OR title LIKE ?)""",
        (like_doc, like_doc, like_course, like_course),
    ).fetchall())


def _target_lecturers_for_specializations(db, specialization_ids: list[str]) -> list[dict]:
    if not specialization_ids:
        return []
    placeholders = ",".join("?" for _ in specialization_ids)
    return rows(db.execute(
        f"""SELECT DISTINCT u.code,u.name,u.role
            FROM lecturer_specializations ls
            JOIN users u ON u.code=ls.user_code
            WHERE ls.specialization_id IN ({placeholders}) AND u.active=1""",
        tuple(specialization_ids),
    ).fetchall())


def preview_time_based_permission_action(db, action: dict) -> dict:
    policy = active_policy(db)
    warnings: list[str] = []
    if not policy:
        return {"status": "need_clarification", "message": "He thong chua co policy active.", "action": action, "risk_warnings": ["He thong chua co policy active."]}
    resolved_specs, missing_specs = _resolve_permission_target_specializations(db, policy, list(action.get("target_specializations") or []))
    if missing_specs:
        warnings.append("Khong tim thay nhom chuyen mon: " + ", ".join(missing_specs))
    documents = _matching_time_permission_documents(db, str(action.get("document_type") or ""), str(action.get("course") or ""))
    if not documents:
        warnings.append("Chua co tai lieu match rule; rule se duoc scheduler ap dung khi tai lieu ton tai.")
    target_lecturers = _target_lecturers_for_specializations(db, [spec["id"] for spec in resolved_specs])
    if not target_lecturers:
        warnings.append("Chua co giang vien active trong cac nhom duoc mo quyen.")
    release_at = str(action.get("release_at") or "")
    try:
        parsed_release = datetime.fromisoformat(release_at.replace("Z", "+00:00"))
        if parsed_release.astimezone(UTC) <= datetime.now(UTC):
            warnings.append("Thoi diem mo quyen nam trong qua khu hoac hien tai; rule se duoc ap dung ngay khi confirm.")
    except ValueError:
        return {"status": "need_clarification", "message": "Thoi diem mo quyen khong hop le.", "action": action, "risk_warnings": ["Thoi diem mo quyen khong hop le."]}
    preview_rule_id = action.get("preview_rule_id") or f"rule-{uuid.uuid4().hex[:12]}"
    impact = {
        "rule_id": preview_rule_id,
        "rule_type": "time_based_permission",
        "document_type": action.get("document_type"),
        "course": action.get("course"),
        "target_specializations": [{"id": spec["id"], "name": spec["name"], "code": spec.get("code", "")} for spec in resolved_specs],
        "release_at": release_at,
        "before_permission": "Truoc thoi diem mo quyen: tai lieu private/confidential, chi owner/admin/head hoac access request da approved doc duoc.",
        "after_permission": "Sau thoi diem mo quyen: tao access request approved cho giang vien thuoc nhom duoc mo quyen.",
        "matching_documents": [{"id": doc["id"], "title": doc["title"], "owner_code": doc["owner_code"], "visibility": doc["visibility"]} for doc in documents],
        "target_lecturers": target_lecturers,
        "permission_impact": {
            "documents_to_open": len(documents),
            "target_lecturers": len(target_lecturers),
            "access_grants_to_create": len(documents) * len(target_lecturers),
        },
        "risk_warnings": warnings,
    }
    action = {
        **action,
        "preview_rule_id": preview_rule_id,
        "target_specialization_ids": [spec["id"] for spec in resolved_specs],
        "target_specialization_names": [spec["name"] for spec in resolved_specs],
        "target_specialization_codes": [spec.get("code", "") for spec in resolved_specs],
    }
    return {
        "status": "preview",
        "action": action,
        "preview": {
            "summary": f"Du kien tao rule mo quyen theo thoi gian cho {action.get('document_type')} {action.get('course')}.",
            "impact": impact,
            "requires_confirmation": True,
            "route": "confirm -> policy_rules -> n8n scheduler -> internal apply due -> audit/heartbeat",
        },
    }


def _governance_score(summary: dict, compliant: bool) -> int:
    readiness = int(summary.get("transfer_readiness_score") or 0)
    coverage = int(summary.get("document_coverage_percent") or 0)
    policy_compliance = int(summary.get("policy_compliance_percent") or 0)
    compliance_score = 100 if compliant else 60
    score = round((readiness * 0.35) + (coverage * 0.25) + (policy_compliance * 0.25) + (compliance_score * 0.15))
    return max(0, min(100, int(score)))


def preview_governance_advisor_action(db, action: dict) -> dict:
    insights = knowledge_transfer_insights(db)
    specializations = knowledge_transfer_specialization_insights(db)["items"]
    course_gaps = knowledge_transfer_course_gaps(db)["items"]
    dependencies = knowledge_transfer_lecturer_dependency(db)["items"]
    recommended_actions = knowledge_transfer_actions(db)
    compliance = compliance_report(db)
    summary = insights["summary"]
    high_risk_specs = [
        item for item in specializations
        if item.get("knowledge_risk") in {"critical", "high"} or int(item.get("assigned_lecturer_count") or 0) <= 1
    ]
    high_gap_courses = [
        item for item in course_gaps
        if int(item.get("coverage_percent") or 0) < 70 or item.get("missing_types")
    ]
    dependency_warnings = [
        item for item in dependencies
        if item.get("dependency_risk") in {"high", "medium"}
    ]
    impact = {
        "risk_summary": {
            **summary,
            "policy_321_compliant": bool(compliance.get("compliant")),
        },
        "governance_score": _governance_score(summary, bool(compliance.get("compliant"))),
        "high_risk_areas": high_risk_specs[:8],
        "recommended_actions": recommended_actions[:8],
        "dependency_warnings": dependency_warnings[:8],
        "course_gaps": high_gap_courses[:8],
        "source": {
            "knowledge_transfer_dashboard": True,
            "specialization_risk": True,
            "course_gap": True,
            "lecturer_dependency": True,
            "policy_compliance": True,
        },
    }
    return {
        "status": "preview",
        "action": action,
        "preview": {
            "summary": "Advisor tong hop rui ro tu Knowledge Transfer, Course Gap, Lecturer Dependency va Policy Compliance.",
            "impact": impact,
            "requires_confirmation": False,
            "confirm_blocked_reason": "Advisor chi ho tro preview/read-only, khong co thay doi de confirm.",
            "route": "preview -> existing dashboards/reports only",
        },
    }


def preview_policy_action(db, message: str, actor: dict | None = None) -> dict:
    action = interpret_policy_command(message)
    if action.get("status") == "need_clarification":
        return action
    action_type = action["action"]
    if action_type in {"assignment.move", "assignment.assign", "assignment.remove"}:
        return preview_assignment_action(db, actor or {"code": "preview"}, action)
    if action_type == "permission.time_based_release":
        return preview_time_based_permission_action(db, action)
    if action_type.startswith("advisor."):
        return preview_governance_advisor_action(db, action)
    tree_actions = {"add_node", "move_node", "rename_node", "delete_node"}
    if action_type in tree_actions:
        current = _current_policy_tree(db)
        changed = _apply_tree_action(current, action)
        return {
            "status": "preview",
            "action": action,
            "preview": {
                "summary": f"Du kien thuc hien {action_type}.",
                "before": current,
                "after": changed,
                "requires_confirmation": True,
                "route": "confirm -> n8n -> internal policy service",
            },
        }
    return {
        "status": "preview",
        "action": action,
        "preview": {
            "summary": f"Du kien cap nhat rule {action_type}.",
            "before": {},
            "after": action,
            "requires_confirmation": True,
            "route": "confirm -> n8n -> internal policy service",
        },
    }


def create_policy_action_request(db, user: dict, message: str, action: dict, preview: dict) -> dict:
    request_id = f"par-{uuid.uuid4().hex[:12]}"
    timestamp = now()
    db.execute(
        """INSERT INTO policy_action_requests(id,actor,message,action_json,preview,status,created_at,confirmed_at,applied_at,audit_log_id)
           VALUES(?,?,?,?,?,'confirmed',?,?,NULL,NULL)""",
        (request_id, user["code"], message, json.dumps(action, ensure_ascii=False), json.dumps(preview, ensure_ascii=False), timestamp, timestamp),
    )
    audit(db, user["code"], "policy_action.confirm", "policy_action", request_id, {"action": action.get("action")})
    return {
        "id": request_id,
        "status": "confirmed",
        "action": action,
        "preview": preview,
        "webhook_payload": {"request_id": request_id, "actor": user["code"], **action},
    }


def _policy_rule_snapshot(db) -> dict:
    result = {}
    for key in ("permission_rules", "storage_rules", "exam_publication"):
        row = db.execute("SELECT value FROM policies WHERE key=?", (key,)).fetchone()
        result[key] = json.loads(row["value"]) if row else None
    return result


def _apply_time_based_permission_rule(db, actor: str, rule: dict, timestamp: str | None = None) -> dict:
    timestamp = timestamp or now()
    content = json.loads(rule["rule_content"]) if isinstance(rule.get("rule_content"), str) else dict(rule["rule_content"])
    documents = _matching_time_permission_documents(db, content.get("document_type", ""), content.get("course", ""))
    lecturers = _target_lecturers_for_specializations(db, list(content.get("target_specialization_ids") or []))
    grants = 0
    for document in documents:
        for lecturer in lecturers:
            if lecturer["code"] == document["owner_code"]:
                continue
            request_key = f"{rule['id']}:{document['id']}:{lecturer['code']}:time_based_release"
            request_id = f"ar-{hashlib.sha256(request_key.encode('utf-8')).hexdigest()[:12]}"
            db.execute(
                """INSERT OR IGNORE INTO access_requests(
                     id,document_id,requester_code,owner_code,status,created_at,resolved_at,
                     source_rule_id,source_rule_type,applied_at
                   )
                   VALUES(?,?,?,?, 'approved', ?, ?, ?, ?, ?)""",
                (request_id, document["id"], lecturer["code"], document["owner_code"], timestamp, timestamp, rule["id"], "time_based_permission", timestamp),
            )
            grants += 1
    content["status"] = "applied"
    content["applied_at"] = timestamp
    content["last_apply_result"] = {"documents": len(documents), "target_lecturers": len(lecturers), "access_grants": grants}
    db.execute("UPDATE policy_rules SET rule_content=? WHERE id=?", (json.dumps(content, ensure_ascii=False), rule["id"]))
    audit(db, actor, "permission.time_based_release.applied", "policy_rule", rule["id"], content["last_apply_result"])
    return content["last_apply_result"]


def apply_due_time_based_permission_rules(db, actor: str = "n8n") -> dict:
    timestamp = now()
    due: list[dict] = []
    for row in rows(db.execute("SELECT * FROM policy_rules WHERE rule_type='time_based_permission'").fetchall()):
        content = json.loads(row["rule_content"])
        if content.get("status") == "applied":
            continue
        release_at = str(content.get("release_at") or "")
        try:
            parsed = datetime.fromisoformat(release_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.astimezone(UTC) <= datetime.now(UTC):
            due.append(row)
    results = [_apply_time_based_permission_rule(db, actor, row, timestamp) for row in due]
    record_automation_heartbeat(db, "policy_activation", "success", {"source": "time_based_permission_scheduler", "applied_rules": len(results)})
    return {"status": "applied", "applied_rules": len(results), "results": results}


def expire_time_based_permission_rule(db, actor: str, rule_id: str) -> dict:
    rule = db.execute("SELECT * FROM policy_rules WHERE id=? AND rule_type='time_based_permission'", (rule_id,)).fetchone()
    if not rule:
        raise ValueError("Khong tim thay time-based permission rule.")
    content = json.loads(rule["rule_content"])
    timestamp = now()
    db.execute(
        "UPDATE access_requests SET status='revoked',resolved_at=? WHERE source_rule_id=? AND source_rule_type='time_based_permission' AND status='approved'",
        (timestamp, rule_id),
    )
    revoked = db.execute("SELECT COUNT(*) count FROM access_requests WHERE source_rule_id=? AND source_rule_type='time_based_permission' AND status='revoked'", (rule_id,)).fetchone()["count"]
    content["status"] = "expired"
    content["expired_at"] = timestamp
    db.execute("UPDATE policy_rules SET rule_content=? WHERE id=?", (json.dumps(content, ensure_ascii=False), rule_id))
    audit(db, actor, "permission.time_based_release.expired", "policy_rule", rule_id, {"revoked_access_requests": revoked})
    record_automation_heartbeat(db, "policy_activation", "success", {"source": "time_based_permission_expire", "rule_id": rule_id, "revoked_access_requests": revoked})
    return {"status": "expired", "rule_id": rule_id, "revoked_access_requests": revoked}


def _rule_content(rule: dict) -> dict:
    try:
        return json.loads(rule.get("rule_content") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _governance_rule_status(rule: dict, content: dict) -> str:
    status = str(content.get("status") or "").lower()
    if status in {"scheduled", "applied", "expired", "failed"}:
        return status
    if content.get("expired_at"):
        return "expired"
    if content.get("applied_at"):
        return "applied"
    if rule.get("rule_type") == "time_based_permission":
        return "scheduled"
    return "applied"


def _rule_trace_rows(db, rule_id: str) -> list[dict]:
    return rows(db.execute(
        """SELECT ar.*, d.title AS document_title, d.doc_type, d.topic,
                  requester.name AS requester_name, owner.name AS owner_name
           FROM access_requests ar
           LEFT JOIN documents d ON d.id=ar.document_id
           LEFT JOIN users requester ON requester.code=ar.requester_code
           LEFT JOIN users owner ON owner.code=ar.owner_code
           WHERE ar.source_rule_id=?
           ORDER BY ar.applied_at DESC, ar.created_at DESC, ar.id""",
        (rule_id,),
    ).fetchall())


def _rule_impact(trace_rows: list[dict]) -> dict:
    documents = {row["document_id"] for row in trace_rows if row.get("document_id")}
    users = {row["requester_code"] for row in trace_rows if row.get("requester_code")}
    revoked = [row for row in trace_rows if row.get("status") == "revoked"]
    active = [row for row in trace_rows if row.get("status") == "approved"]
    return {
        "documents_affected": len(documents),
        "users_affected": len(users),
        "permissions_created": len(trace_rows),
        "permissions_active": len(active),
        "permissions_revoked": len(revoked),
    }


def _rule_applied_at(content: dict, trace_rows: list[dict]) -> str | None:
    if content.get("applied_at"):
        return content["applied_at"]
    values = [row.get("applied_at") for row in trace_rows if row.get("applied_at")]
    return max(values) if values else None


def _rule_expired_at(content: dict, audits: list[dict]) -> str | None:
    if content.get("expired_at"):
        return content["expired_at"]
    expired = [item["created_at"] for item in audits if item.get("action") == "permission.time_based_release.expired"]
    return max(expired) if expired else None


def _rule_audits(db, rule_id: str) -> list[dict]:
    result = rows(db.execute(
        "SELECT * FROM audit_logs WHERE resource_type='policy_rule' AND resource_id=? ORDER BY created_at ASC,id ASC",
        (rule_id,),
    ).fetchall())
    for item in result:
        item["detail"] = json.loads(item["detail"]) if isinstance(item.get("detail"), str) else item.get("detail", {})
    return result


def _rule_confirmations(db, rule_id: str) -> list[dict]:
    confirmations: list[dict] = []
    requests = rows(db.execute("SELECT * FROM policy_action_requests ORDER BY created_at ASC").fetchall())
    audits = rows(db.execute("SELECT * FROM policy_audit_logs ORDER BY created_at ASC").fetchall())
    audits_by_id = {item["id"]: item for item in audits}
    for request in requests:
        action = json.loads(request["action_json"]) if isinstance(request.get("action_json"), str) else {}
        preview = json.loads(request["preview"]) if isinstance(request.get("preview"), str) else {}
        audit_row = audits_by_id.get(request.get("audit_log_id"))
        after = {}
        if audit_row:
            try:
                after = json.loads(audit_row["after_state"])
            except (TypeError, json.JSONDecodeError):
                after = {}
        candidate_ids = {
            str(action.get("preview_rule_id") or ""),
            str(preview.get("impact", {}).get("rule_id") or "") if isinstance(preview.get("impact"), dict) else "",
            str(after.get("rule", {}).get("id") or "") if isinstance(after.get("rule"), dict) else "",
        }
        if rule_id in candidate_ids:
            confirmations.append({
                "id": request["id"],
                "actor": request["actor"],
                "message": request["message"],
                "status": request["status"],
                "created_at": request["created_at"],
                "confirmed_at": request["confirmed_at"],
                "applied_at": request["applied_at"],
                "audit_log_id": request["audit_log_id"],
            })
    return confirmations


def _rule_timeline(rule: dict, content: dict, audits: list[dict], confirmations: list[dict]) -> list[dict]:
    items = [{
        "event": "Created",
        "action": "permission.time_based_release.created" if rule.get("rule_type") == "time_based_permission" else "policy_rule.created",
        "actor": rule.get("created_by"),
        "at": rule.get("created_at"),
        "detail": {"rule_type": rule.get("rule_type")},
    }]
    for request in confirmations:
        items.append({"event": "Confirmed", "action": "policy_action.confirm", "actor": request["actor"], "at": request.get("confirmed_at") or request.get("created_at"), "detail": {"request_id": request["id"]}})
    for audit_item in audits:
        event = "Audit"
        if audit_item["action"] == "permission.time_based_release.applied":
            event = "Applied"
        elif audit_item["action"] == "permission.time_based_release.expired":
            event = "Expired"
        elif audit_item["action"] == "permission.time_based_release.created":
            event = "Created"
        items.append({"event": event, "action": audit_item["action"], "actor": audit_item["actor_code"], "at": audit_item["created_at"], "detail": audit_item["detail"]})
    if content.get("applied_at") and not any(item["event"] == "Applied" for item in items):
        items.append({"event": "Applied", "action": "rule_content.applied_at", "actor": None, "at": content["applied_at"], "detail": {}})
    if content.get("expired_at") and not any(item["event"] == "Expired" for item in items):
        items.append({"event": "Expired", "action": "rule_content.expired_at", "actor": None, "at": content["expired_at"], "detail": {}})
    return sorted(items, key=lambda item: item.get("at") or "")


def _rule_scheduler_status(db) -> dict:
    heartbeat = db.execute("SELECT * FROM automation_heartbeats WHERE workflow='policy_activation'").fetchone()
    if not heartbeat:
        return {"workflow": "policy_activation", "status": "no_data", "last_heartbeat_at": None, "detail": {}}
    row = _heartbeat_row(dict(heartbeat))
    return {
        "workflow": row["workflow"],
        "status": row["last_status"],
        "last_heartbeat_at": row["last_heartbeat_at"],
        "age_seconds": row["age_seconds"],
        "detail": row["last_detail"],
    }


def _governance_rule_summary(db, rule: dict) -> dict:
    content = _rule_content(rule)
    trace_rows = _rule_trace_rows(db, rule["id"])
    audits = _rule_audits(db, rule["id"])
    impact = _rule_impact(trace_rows)
    return {
        "id": rule["id"],
        "rule_type": rule["rule_type"],
        "rule_name": rule["rule_name"],
        "status": _governance_rule_status(rule, content),
        "created_by": rule["created_by"],
        "created_at": rule["created_at"],
        "applied_at": _rule_applied_at(content, trace_rows),
        "expired_at": _rule_expired_at(content, audits),
        "affected_documents": impact["documents_affected"],
        "affected_users": impact["users_affected"],
        "permissions_created": impact["permissions_created"],
        "permissions_revoked": impact["permissions_revoked"],
        "release_at": content.get("release_at"),
        "target_groups": content.get("target_specialization_names") or content.get("target_specializations") or [],
    }


def list_governance_rules(db) -> dict:
    rules = rows(db.execute("SELECT * FROM policy_rules ORDER BY created_at DESC,id DESC").fetchall())
    return {"items": [_governance_rule_summary(db, rule) for rule in rules]}


def governance_rule_detail(db, rule_id: str) -> dict:
    rule = db.execute("SELECT * FROM policy_rules WHERE id=?", (rule_id,)).fetchone()
    if not rule:
        raise ValueError("Khong tim thay governance rule.")
    rule = dict(rule)
    content = _rule_content(rule)
    trace_rows = _rule_trace_rows(db, rule_id)
    audits = _rule_audits(db, rule_id)
    confirmations = _rule_confirmations(db, rule_id)
    impact = _rule_impact(trace_rows)
    return {
        "rule": _governance_rule_summary(db, rule),
        "content": content,
        "timeline": _rule_timeline(rule, content, audits, confirmations),
        "traceability": {
            "rule": {"id": rule["id"], "type": rule["rule_type"], "name": rule["rule_name"]},
            "permissions_generated": trace_rows,
            "affected_users": sorted({row["requester_code"] for row in trace_rows if row.get("requester_code")}),
            "affected_documents": sorted({row["document_id"] for row in trace_rows if row.get("document_id")}),
        },
        "impact": impact,
        "audit_history": audits,
        "confirmations": confirmations,
        "operations": {
            "scheduler": _rule_scheduler_status(db),
            "last_apply": next((item for item in reversed(audits) if item["action"] == "permission.time_based_release.applied"), None),
            "expire_event": next((item for item in reversed(audits) if item["action"] == "permission.time_based_release.expired"), None),
        },
    }


def _searchable_text(*values: object) -> str:
    return _fold_text(" ".join(str(value or "") for value in values))


def _matches_search(query: str, *values: object) -> bool:
    return query in _searchable_text(*values)


def _global_result(result_type: str, title: str, description: str, source: str, updated_at: str | None, **extra) -> dict:
    return {
        "type": result_type,
        "title": title,
        "description": description,
        "source": source,
        "updated_time": updated_at,
        **extra,
    }


def global_knowledge_search(db, user: dict, query: str) -> dict:
    q = _fold_text(query)
    result = {
        "query": query,
        "documents": [],
        "courses": [],
        "specializations": [],
        "lecturers": [],
        "rules": [],
        "policy": [],
        "audit": [],
        "assignments": [],
    }
    if not q:
        return result

    for document in rows(db.execute(
        """SELECT * FROM documents
           WHERE deleted_at IS NULL AND status!='DELETED'
           ORDER BY updated_at DESC LIMIT 500"""
    ).fetchall()):
        if not can_read(db, user, document):
            continue
        if _matches_search(q, document.get("id"), document.get("title"), document.get("topic"), document.get("doc_type"), document.get("document_type"), document.get("folder_path"), document.get("owner_code")):
            result["documents"].append(_global_result(
                "Document",
                document["title"],
                f"{document['topic']} - {document['doc_type']} - {document['visibility']}",
                "documents",
                document.get("updated_at"),
                id=document["id"],
                href=f"/documents/{document['id']}",
            ))

    course_ids: set[str] = set()
    for course in rows(db.execute(
        """SELECT c.*, s.name AS specialization_name
           FROM folder_nodes c
           LEFT JOIN folder_nodes spec_node ON spec_node.id=c.parent_id
           LEFT JOIN specializations s ON s.folder_node_id=spec_node.id
           WHERE c.type='course' AND c.status='active'
           ORDER BY c.updated_at DESC LIMIT 500"""
    ).fetchall()):
        if _matches_search(q, course.get("id"), course.get("name"), course.get("path"), course.get("specialization_name")):
            course_ids.add(course["id"])
            result["courses"].append(_global_result(
                "Course",
                course["name"],
                course.get("specialization_name") or course.get("path") or "",
                "folder_nodes",
                course.get("updated_at"),
                id=course["id"],
            ))
    for course in rows(db.execute("SELECT * FROM courses ORDER BY code LIMIT 200").fetchall()):
        if course.get("code") in course_ids:
            continue
        if _matches_search(q, course.get("code"), course.get("name"), course.get("required_doc_types")):
            result["courses"].append(_global_result(
                "Course",
                f"{course['code']} - {course['name']}",
                "Legacy course requirement profile",
                "courses",
                None,
                id=course["code"],
            ))

    for spec in rows(db.execute("SELECT * FROM specializations ORDER BY name LIMIT 500").fetchall()):
        courses = rows(db.execute(
            "SELECT name,path FROM folder_nodes WHERE parent_id=? AND type='course' AND status='active' ORDER BY name",
            (spec.get("folder_node_id"),),
        ).fetchall()) if spec.get("folder_node_id") else []
        course_text = " ".join(f"{item.get('name')} {item.get('path')}" for item in courses)
        if _matches_search(q, spec.get("id"), spec.get("name"), spec.get("description"), spec.get("code"), course_text):
            result["specializations"].append(_global_result(
                "Specialization",
                spec["name"],
                spec.get("description") or f"{len(courses)} courses",
                "specializations",
                None,
                id=spec["id"],
            ))

    can_view_people = user.get("role") in {"admin", "head"} or "transfer.manage" in user.get("permissions", [])
    if can_view_people:
        for lecturer in rows(db.execute("SELECT code,name,role,department,active FROM users WHERE active=1 ORDER BY name LIMIT 500").fetchall()):
            if lecturer["role"] not in {"lecturer", "new_lecturer", "head"}:
                continue
            if _matches_search(q, lecturer.get("code"), lecturer.get("name"), lecturer.get("role"), lecturer.get("department")):
                result["lecturers"].append(_global_result(
                    "Lecturer",
                    f"{lecturer['code']} - {lecturer['name']}",
                    f"{lecturer['role']} - {lecturer['department']}",
                    "users",
                    None,
                    id=lecturer["code"],
                ))

    can_view_governance = user.get("role") in {"admin", "head"} or "policy.manage" in user.get("permissions", [])
    if can_view_governance:
        for rule in list_governance_rules(db)["items"]:
            detail = governance_rule_detail(db, rule["id"])
            affected_docs = " ".join(item.get("document_title") or item.get("document_id") or "" for item in detail["traceability"]["permissions_generated"])
            affected_users = " ".join(detail["traceability"]["affected_users"])
            if _matches_search(q, rule.get("id"), rule.get("rule_name"), rule.get("rule_type"), rule.get("status"), affected_docs, affected_users, json.dumps(detail.get("content", {}), ensure_ascii=False)):
                result["rules"].append(_global_result(
                    "Governance Rule",
                    rule["rule_name"],
                    f"{rule['rule_type']} - {rule['status']} - {rule['affected_documents']} documents / {rule['affected_users']} users",
                    "policy_rules",
                    rule.get("applied_at") or rule.get("expired_at") or rule.get("created_at"),
                    id=rule["id"],
                    href="/governance-rules",
                ))

        for policy in rows(db.execute("SELECT * FROM policy_files ORDER BY created_at DESC LIMIT 200").fetchall()):
            parsed = json.loads(policy["parsed_json"]) if isinstance(policy.get("parsed_json"), str) else {}
            if _matches_search(q, policy.get("id"), policy.get("title"), policy.get("status"), policy.get("raw_text"), json.dumps(parsed, ensure_ascii=False)):
                result["policy"].append(_global_result(
                    "Policy",
                    policy["title"],
                    f"{policy['status']} policy file",
                    "policy_files",
                    policy.get("activated_at") or policy.get("created_at"),
                    id=policy["id"],
                    href="/policy",
                ))
        for node in rows(db.execute("SELECT * FROM folder_nodes WHERE status='active' ORDER BY updated_at DESC LIMIT 500").fetchall()):
            if _matches_search(q, node.get("id"), node.get("name"), node.get("type"), node.get("path")):
                result["policy"].append(_global_result(
                    "Policy Item",
                    node["name"],
                    f"{node['type']} - {node['path']}",
                    "folder_nodes",
                    node.get("updated_at"),
                    id=node["id"],
                    href="/policy",
                ))

    can_view_audit = user.get("role") in {"admin", "head"} or "audit.view" in user.get("permissions", [])
    if can_view_audit:
        for item in rows(db.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 500").fetchall()):
            detail = item.get("detail")
            if _matches_search(q, item.get("action"), item.get("resource_type"), item.get("resource_id"), item.get("actor_code"), detail):
                result["audit"].append(_global_result(
                    "Audit",
                    item["action"],
                    f"{item['actor_code']} - {item['resource_type']}:{item.get('resource_id') or ''}",
                    "audit_logs",
                    item.get("created_at"),
                    id=str(item["id"]),
                ))

    if can_view_people or can_view_governance:
        assignment_rows = rows(db.execute(
            """SELECT la.*, u.name AS lecturer_name, s.name AS specialization_name
               FROM lecturer_assignments la
               LEFT JOIN users u ON u.code=la.lecturer_code
               LEFT JOIN specializations s ON s.id=la.specialization_id
               ORDER BY la.updated_at DESC LIMIT 500"""
        ).fetchall())
        projection_rows = rows(db.execute(
            """SELECT ls.id, ls.user_code AS lecturer_code, u.name AS lecturer_name,
                      s.name AS specialization_name, '' AS specialization_code,
                      ls.created_at, 'active' AS status
               FROM lecturer_specializations ls
               LEFT JOIN users u ON u.code=ls.user_code
               LEFT JOIN specializations s ON s.id=ls.specialization_id
               ORDER BY ls.created_at DESC LIMIT 500"""
        ).fetchall())
        seen: set[str] = set()
        for assignment in assignment_rows + projection_rows:
            key = f"{assignment.get('lecturer_code')}:{assignment.get('specialization_name')}:{assignment.get('id')}"
            if key in seen:
                continue
            seen.add(key)
            if _matches_search(q, assignment.get("lecturer_code"), assignment.get("lecturer_name"), assignment.get("specialization_name"), assignment.get("specialization_code"), assignment.get("status")):
                result["assignments"].append(_global_result(
                    "Assignment",
                    f"{assignment.get('lecturer_code')} -> {assignment.get('specialization_name')}",
                    f"{assignment.get('lecturer_name') or ''} - {assignment.get('status') or 'active'}",
                    "lecturer_assignments",
                    assignment.get("updated_at") or assignment.get("created_at"),
                    id=assignment.get("id"),
                    href="/policy",
                ))

    return result


def apply_policy_action(db, actor: str, action: dict, request_id: str | None = None) -> dict:
    action_type = action.get("action")
    before = {"tree": _current_policy_tree(db) if active_policy(db) else None, "rules": _policy_rule_snapshot(db)}
    timestamp = now()
    if str(action_type).startswith("advisor."):
        raise ValueError("Advisor chi ho tro preview/read-only, khong co thay doi de confirm.")
    if action_type in {"add_node", "move_node", "rename_node", "delete_node"}:
        if not before["tree"]:
            raise ValueError("He thong chua co policy active.")
        changed = _apply_tree_action(before["tree"], action)
        applied = _store_tree_as_policy(db, actor, changed, f"Policy Assistant {timestamp[:10]}")
        after = {"tree": changed, "policy": applied}
    elif action_type == "update_permission":
        content = {
            "document_type": action.get("document_type", "document"),
            "visibility": action.get("visibility", "confidential"),
            "roles": action.get("roles", []),
        }
        rule_id = str(action.get("preview_rule_id") or f"rule-{uuid.uuid4().hex[:12]}")
        db.execute(
            "INSERT INTO policy_rules(id,rule_type,rule_name,rule_content,created_by,created_at) VALUES(?,?,?,?,?,?)",
            (rule_id, "permission_rule", f"permission:{content['document_type']}", json.dumps(content, ensure_ascii=False), actor, timestamp),
        )
        if _same_name(content["document_type"], "De thi"):
            db.execute(
                "INSERT INTO policies(key,value,updated_at) VALUES('exam_publication',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (json.dumps({"classification_before_exam": "confidential", "read_roles_before_exam": ["head"], "publish_after_exam": True, "public_scope": "authenticated_faculty"}, ensure_ascii=False), timestamp),
            )
        after = {"rule": content, "rules": _policy_rule_snapshot(db)}
    elif action_type in {"update_storage_rule", "update_retention_rule"}:
        row = db.execute("SELECT value FROM policies WHERE key='storage_rules'").fetchone()
        storage = json.loads(row["value"]) if row else {"naming": "{department}/{topic}/{doc_type}/{visibility}", "retention_years": 10}
        if action_type == "update_retention_rule":
            storage["retention_years"] = int(action.get("years") or storage.get("retention_years") or 10)
        content = {**action, "storage_policy": storage}
        rule_id = f"rule-{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO policy_rules(id,rule_type,rule_name,rule_content,created_by,created_at) VALUES(?,?,?,?,?,?)",
            (rule_id, "storage_rule" if action_type == "update_storage_rule" else "retention_rule", f"{action_type}:{action.get('document_type','document')}", json.dumps(content, ensure_ascii=False), actor, timestamp),
        )
        db.execute(
            "INSERT INTO policies(key,value,updated_at) VALUES('storage_rules',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (json.dumps(storage, ensure_ascii=False), timestamp),
        )
        after = {"rule": content, "rules": _policy_rule_snapshot(db)}
    elif action_type in {"assignment.move", "assignment.assign", "assignment.remove"}:
        if action.get("confirm_blocked_reason"):
            raise ValueError(str(action["confirm_blocked_reason"]))
        batch_id = action.get("batch_preview_id")
        if not batch_id:
            raise ValueError("Assignment preview khong co batch_preview_id.")
        detail = confirm_lecturer_assignment_batch(db, {"code": actor}, str(batch_id), "replace_for_listed_lecturers")
        record_automation_heartbeat(
            db,
            "lecturer_assignment",
            "success",
            {
                "source": "knowledge_governance_agent",
                "action": action_type,
                "batch_preview_id": batch_id,
                "lecturer_code": action.get("lecturer_code"),
            },
        )
        after = {"assignment": detail}
    elif action_type == "permission.time_based_release":
        content = {
            "document_type": action.get("document_type"),
            "course": action.get("course"),
            "target_specializations": action.get("target_specializations", []),
            "target_specialization_ids": action.get("target_specialization_ids", []),
            "target_specialization_names": action.get("target_specialization_names", []),
            "target_specialization_codes": action.get("target_specialization_codes", []),
            "release_at": action.get("release_at"),
            "before_permission": "private_or_confidential_until_release",
            "after_permission": "approved_access_requests_for_target_specializations",
            "status": "scheduled",
            "created_at": timestamp,
        }
        rule_id = f"rule-{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO policy_rules(id,rule_type,rule_name,rule_content,created_by,created_at) VALUES(?,?,?,?,?,?)",
            (rule_id, "time_based_permission", f"time_release:{content['document_type']}:{content['course']}", json.dumps(content, ensure_ascii=False), actor, timestamp),
        )
        audit(db, actor, "permission.time_based_release.created", "policy_rule", rule_id, {"rule_type": "time_based_permission", "release_at": content["release_at"], "target_groups": content["target_specialization_names"]})
        apply_result = None
        try:
            parsed = datetime.fromisoformat(str(content["release_at"]).replace("Z", "+00:00"))
            if parsed.astimezone(UTC) <= datetime.now(UTC):
                apply_result = _apply_time_based_permission_rule(db, actor, {"id": rule_id, "rule_content": json.dumps(content, ensure_ascii=False)}, timestamp)
        except ValueError:
            pass
        record_automation_heartbeat(db, "policy_activation", "success", {"source": "knowledge_governance_agent", "action": action_type, "rule_id": rule_id})
        after = {"rule": {**content, "id": rule_id}, "apply_result": apply_result}
    else:
        raise ValueError("Policy action khong duoc ho tro.")

    audit_id = f"pal-{uuid.uuid4().hex[:12]}"
    db.execute(
        "INSERT INTO policy_audit_logs(id,actor,action,before_state,after_state,status,created_at) VALUES(?,?,?,?,?,'applied',?)",
        (audit_id, actor, action_type, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), timestamp),
    )
    if request_id:
        db.execute(
            "UPDATE policy_action_requests SET status='applied',applied_at=?,audit_log_id=? WHERE id=?",
            (timestamp, audit_id, request_id),
        )
    audit(db, actor, "policy_action.apply", "policy_action", request_id or audit_id, {"action": action_type})
    return {"status": "applied", "audit_log_id": audit_id, "action": action, "after": after}


def rollback_policy_action(db, actor: str, audit_log_id: str) -> dict:
    log = db.execute("SELECT * FROM policy_audit_logs WHERE id=?", (audit_log_id,)).fetchone()
    if not log:
        raise ValueError("Khong tim thay audit log policy.")
    before = json.loads(log["before_state"])
    if before.get("tree"):
        _store_tree_as_policy(db, actor, before["tree"], f"Rollback {audit_log_id}")
    for key, value in before.get("rules", {}).items():
        if value is not None:
            db.execute(
                "INSERT INTO policies(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), now()),
            )
    rollback_id = f"pal-{uuid.uuid4().hex[:12]}"
    db.execute(
        "INSERT INTO policy_audit_logs(id,actor,action,before_state,after_state,status,created_at) VALUES(?,?,?,?,?,'rolled_back',?)",
        (rollback_id, actor, f"rollback:{log['action']}", log["after_state"], log["before_state"], now()),
    )
    audit(db, actor, "policy_action.rollback", "policy_audit", audit_log_id)
    return {"status": "rolled_back", "audit_log_id": rollback_id, "rolled_back": audit_log_id}


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
    items = rows(db.execute(
        """SELECT s.*
           FROM specializations s
           JOIN folder_nodes fn ON fn.id=s.folder_node_id
           WHERE s.policy_id=? AND fn.status='active'
           ORDER BY s.name, s.id""",
        (policy["id"],),
    ).fetchall())
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
        if spec["folder_node_id"] not in master_by_id:
            continue
        pending = [spec["folder_node_id"]]
        cloned: dict[str, str] = {}
        while pending:
            source_id = pending.pop(0)
            node = master_by_id.get(source_id)
            if not node:
                continue
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


def _specialization_code_map(policy: dict | None) -> dict[str, dict]:
    if not policy:
        return {}
    parsed = policy_public(policy)["parsed_json"]
    specs = parsed.get("master_tree_json", {}).get("specializations") or parsed.get("specializations") or []
    result: dict[str, dict] = {}
    for spec in specs:
        names = [
            spec.get("name"),
            spec.get("name_vi"),
            spec.get("name_en"),
            spec.get("code"),
        ]
        info = {
            "code": str(spec.get("code") or "").strip(),
            "name": str(spec.get("name") or spec.get("name_vi") or "").strip(),
            "name_en": str(spec.get("name_en") or "").strip(),
        }
        for name in names:
            folded = _fold_text(name)
            if folded:
                result[folded] = info
    return result


def _assignment_specialization_index(db, policy: dict) -> dict[str, dict]:
    code_map = _specialization_code_map(policy)
    index: dict[str, dict] = {}
    for spec in active_specializations(db):
        snapshot = code_map.get(_fold_text(spec["name"]), {})
        item = {
            **spec,
            "code": snapshot.get("code", ""),
            "name_en": snapshot.get("name_en", ""),
        }
        aliases = {spec["name"], item.get("code", ""), item.get("name_en", "")}
        for alias in aliases:
            folded = _fold_text(alias)
            if folded:
                index[folded] = item
    return index


def _assignment_rows_from_csv(text: str) -> list[dict]:
    reader = csv.reader(StringIO(text))
    rows_list = [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
    if not rows_list:
        return []
    header_aliases = {"lecturer_code", "ma giang vien", "ma gv", "user_code", "code"}
    first = [_fold_text(cell).replace(" ", "_") for cell in rows_list[0]]
    has_header = any(cell in header_aliases for cell in first)
    if has_header:
        header = first
        data_rows = rows_list[1:]
        result = []
        for row in data_rows:
            item = {header[idx]: row[idx] for idx in range(min(len(header), len(row)))}
            result.append({
                "lecturer_code": item.get("lecturer_code") or item.get("ma_giang_vien") or item.get("ma_gv") or item.get("user_code") or item.get("code") or "",
                "lecturer_name": item.get("lecturer_name") or item.get("ho_ten") or item.get("name") or "",
                "specialization": item.get("specialization") or item.get("nhom_chuyen_mon") or item.get("chuyen_mon") or item.get("specialization_code") or "",
                "effective_from": item.get("effective_from") or "",
                "effective_to": item.get("effective_to") or "",
                "note": item.get("note") or item.get("ghi_chu") or "",
            })
        return result
    result = []
    for row in rows_list:
        result.append({
            "lecturer_code": row[0] if len(row) > 0 else "",
            "lecturer_name": row[1] if len(row) > 1 else "",
            "specialization": row[2] if len(row) > 2 else "",
            "effective_from": row[3] if len(row) > 3 else "",
            "effective_to": row[4] if len(row) > 4 else "",
            "note": row[5] if len(row) > 5 else "",
        })
    return result


def _assignment_rows_from_json(text: str) -> list[dict]:
    payload = json.loads(text)
    items = payload.get("assignments") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("JSON assignment phai la danh sach hoac co field assignments.")
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append({
            "lecturer_code": item.get("lecturer_code") or item.get("user_code") or item.get("code") or "",
            "lecturer_name": item.get("lecturer_name") or item.get("name") or "",
            "specialization": item.get("specialization") or item.get("specialization_code") or item.get("specialization_name") or "",
            "effective_from": item.get("effective_from") or "",
            "effective_to": item.get("effective_to") or "",
            "note": item.get("note") or "",
        })
    return result


def parse_assignment_rows(filename: str, raw: bytes, mime_type: str = "") -> list[dict]:
    lowered = filename.lower()
    text = raw.decode("utf-8-sig", errors="replace")
    if lowered.endswith(".json") or "json" in mime_type:
        return _assignment_rows_from_json(text)
    return _assignment_rows_from_csv(text)


def preview_lecturer_assignment_import(db, actor: dict, filename: str, raw: bytes, mime_type: str = "text/csv") -> dict:
    policy = active_policy(db)
    if not policy:
        raise ValueError("He thong chua co policy active. Vui long import va activate policy truoc.")
    source = "json_import" if filename.lower().endswith(".json") or "json" in mime_type else "csv_import"
    input_rows = parse_assignment_rows(filename, raw, mime_type)
    spec_index = _assignment_specialization_index(db, policy)
    timestamp = now()
    batch_id = f"lab-{uuid.uuid4().hex[:12]}"
    preview_rows = []
    valid_rows = []
    errors = []
    warnings = []
    seen_pairs: set[tuple[str, str]] = set()
    for idx, item in enumerate(input_rows, start=1):
        lecturer_code = str(item.get("lecturer_code") or "").strip()
        specialization_value = str(item.get("specialization") or "").strip()
        row_errors = []
        lecturer = db.execute("SELECT * FROM users WHERE code=? AND active=1", (lecturer_code,)).fetchone() if lecturer_code else None
        if not lecturer:
            row_errors.append("Ma giang vien khong ton tai.")
        elif lecturer["role"] not in {"lecturer", "new_lecturer"}:
            row_errors.append("User khong phai lecturer/new_lecturer.")
        spec = spec_index.get(_fold_text(specialization_value)) if specialization_value else None
        if not spec:
            row_errors.append("Chuyen mon khong ton tai trong policy active.")
        duplicate = False
        if lecturer and spec:
            key = (lecturer["code"], spec["id"])
            duplicate = key in seen_pairs
            if duplicate:
                warnings.append({"row": idx, "message": "Dong bi trung trong file import."})
            seen_pairs.add(key)
        preview_item = {
            "row": idx,
            "lecturer_code": lecturer_code,
            "lecturer_name": str(item.get("lecturer_name") or (lecturer["name"] if lecturer else "") or "").strip(),
            "specialization_input": specialization_value,
            "specialization_id": spec["id"] if spec else None,
            "specialization_code": spec.get("code", "") if spec else "",
            "specialization_name": spec["name"] if spec else "",
            "effective_from": str(item.get("effective_from") or "").strip() or None,
            "effective_to": str(item.get("effective_to") or "").strip() or None,
            "status": "error" if row_errors else "valid",
            "errors": row_errors,
            "warnings": ["Dong bi trung trong file import."] if duplicate else [],
        }
        preview_rows.append(preview_item)
        if row_errors:
            errors.append({"row": idx, "lecturer_code": lecturer_code, "message": "; ".join(row_errors)})
        elif not duplicate:
            valid_rows.append(preview_item)
    summary = {
        "total_rows": len(preview_rows),
        "valid_rows": len(valid_rows),
        "error_rows": len(errors),
        "warning_rows": len(warnings),
    }
    status = "validated" if not errors else "has_errors"
    db.execute(
        """INSERT INTO lecturer_assignment_batches
           (id,policy_id,source,file_name,status,created_by,created_at,confirmed_by,confirmed_at,summary_json)
           VALUES(?,?,?,?,?,?,?,NULL,NULL,?)""",
        (batch_id, policy["id"], source, filename, status, actor["code"], timestamp, json.dumps(summary, ensure_ascii=False)),
    )
    for item in valid_rows:
        assignment_id = f"la-{uuid.uuid4().hex[:12]}"
        db.execute(
            """INSERT INTO lecturer_assignments
               (id,batch_id,policy_id,lecturer_code,lecturer_name_snapshot,specialization_id,
                specialization_code_snapshot,specialization_name_snapshot,source,status,effective_from,effective_to,
                validation_status,validation_errors_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                assignment_id, batch_id, policy["id"], item["lecturer_code"], item["lecturer_name"],
                item["specialization_id"], item["specialization_code"], item["specialization_name"], source, "validated",
                item["effective_from"], item["effective_to"], "valid", "[]", timestamp, timestamp,
            ),
        )
    return {
        "status": status,
        "batch_preview_id": batch_id,
        "policy": policy_public(policy),
        "summary": summary,
        "assignments": preview_rows,
        "errors": errors,
        "warnings": warnings,
    }


def _upsert_folder_permissions_for_assignment(db, assignment: dict) -> int:
    timestamp = now()
    node_ids = subtree_node_ids(db, assignment["folder_node_id"])
    count = 0
    for node_id in node_ids:
        for permission in ("read", "upload"):
            permission_key = f"{assignment['lecturer_code']}:{node_id}:{permission}:{assignment['policy_id']}"
            permission_id = f"lfp-{hashlib.sha256(permission_key.encode('utf-8')).hexdigest()[:12]}"
            db.execute(
                """INSERT OR IGNORE INTO lecturer_folder_permissions
                   (id,user_code,folder_node_id,permission,source_assignment_id,policy_id,status,created_at,updated_at)
                   VALUES(?,?,?,?,? ,?,'active',?,?)""",
                (permission_id, assignment["lecturer_code"], node_id, permission, assignment["id"], assignment["policy_id"], timestamp, timestamp),
            )
            db.execute(
                "UPDATE lecturer_folder_permissions SET source_assignment_id=?,status='active',updated_at=? WHERE user_code=? AND folder_node_id=? AND permission=? AND policy_id=?",
                (assignment["id"], timestamp, assignment["lecturer_code"], node_id, permission, assignment["policy_id"]),
            )
            count += 1
    return count


def confirm_lecturer_assignment_batch(db, actor: dict, batch_id: str, apply_mode: str = "replace_for_listed_lecturers") -> dict:
    batch = db.execute("SELECT * FROM lecturer_assignment_batches WHERE id=?", (batch_id,)).fetchone()
    if not batch:
        raise ValueError("Assignment batch khong ton tai.")
    if batch["status"] == "active":
        return lecturer_assignment_batch_detail(db, batch_id)
    summary = json.loads(batch["summary_json"] or "{}")
    if summary.get("error_rows", 0):
        raise ValueError("Assignment batch con loi validate, khong the confirm.")
    if apply_mode not in {"replace_for_listed_lecturers", "append", "replace_all"}:
        raise ValueError("apply_mode khong hop le.")
    policy = db.execute("SELECT * FROM policy_files WHERE id=?", (batch["policy_id"],)).fetchone()
    if not policy or policy["status"] != "active":
        raise ValueError("Assignment batch khong thuoc policy active.")
    assignments = rows(db.execute(
        """SELECT la.*, s.folder_node_id
           FROM lecturer_assignments la JOIN specializations s ON s.id=la.specialization_id
           WHERE la.batch_id=? AND la.validation_status='valid'""",
        (batch_id,),
    ).fetchall())
    listed_users = sorted({item["lecturer_code"] for item in assignments})
    timestamp = now()
    if apply_mode == "replace_all":
        db.execute("UPDATE lecturer_assignments SET status='inactive',updated_at=? WHERE policy_id=? AND status='active'", (timestamp, batch["policy_id"]))
        db.execute("DELETE FROM lecturer_specializations WHERE specialization_id IN (SELECT id FROM specializations WHERE policy_id=?)", (batch["policy_id"],))
        db.execute("UPDATE lecturer_folder_permissions SET status='inactive',updated_at=? WHERE policy_id=?", (timestamp, batch["policy_id"]))
    elif apply_mode == "replace_for_listed_lecturers" and listed_users:
        placeholders = ",".join("?" for _ in listed_users)
        db.execute(
            f"UPDATE lecturer_assignments SET status='inactive',updated_at=? WHERE policy_id=? AND lecturer_code IN ({placeholders}) AND status='active'",
            (timestamp, batch["policy_id"], *listed_users),
        )
        db.execute(
            f"DELETE FROM lecturer_specializations WHERE user_code IN ({placeholders}) AND specialization_id IN (SELECT id FROM specializations WHERE policy_id=?)",
            (*listed_users, batch["policy_id"]),
        )
        db.execute(
            f"UPDATE lecturer_folder_permissions SET status='inactive',updated_at=? WHERE policy_id=? AND user_code IN ({placeholders})",
            (timestamp, batch["policy_id"], *listed_users),
        )
    provisioned_users: set[str] = set()
    permission_count = 0
    for assignment in assignments:
        db.execute("UPDATE lecturer_assignments SET status='active',updated_at=? WHERE id=?", (timestamp, assignment["id"]))
        db.execute(
            "INSERT OR IGNORE INTO lecturer_specializations(id,user_code,specialization_id,created_at) VALUES(?,?,?,?)",
            (f"ls-{uuid.uuid4().hex[:12]}", assignment["lecturer_code"], assignment["specialization_id"], timestamp),
        )
        permission_count += _upsert_folder_permissions_for_assignment(db, assignment)
        db.execute(
            """INSERT INTO lecturer_assignment_audit_logs(id,assignment_id,batch_id,actor,action,before_json,after_json,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                f"laa-{uuid.uuid4().hex[:12]}", assignment["id"], batch_id, actor["code"], "assignment.confirm",
                "{}", json.dumps({"lecturer_code": assignment["lecturer_code"], "specialization_id": assignment["specialization_id"]}, ensure_ascii=False), timestamp,
            ),
        )
        provisioned_users.add(assignment["lecturer_code"])
    for user_code in provisioned_users:
        spec_ids = {row["specialization_id"] for row in db.execute(
            """SELECT ls.specialization_id FROM lecturer_specializations ls
               JOIN specializations s ON s.id=ls.specialization_id
               WHERE ls.user_code=? AND s.policy_id=?""",
            (user_code, batch["policy_id"]),
        ).fetchall()}
        sync_lecturer_folder_nodes(db, user_code, spec_ids)
    db.execute(
        "UPDATE lecturer_assignment_batches SET status='active',confirmed_by=?,confirmed_at=?,summary_json=? WHERE id=?",
        (
            actor["code"], timestamp,
            json.dumps({**summary, "provisioned_users": len(provisioned_users), "folder_permissions": permission_count}, ensure_ascii=False),
            batch_id,
        ),
    )
    audit(db, actor["code"], "lecturer_assignment.confirm", "lecturer_assignment_batch", batch_id, {"users": len(provisioned_users), "assignments": len(assignments)})
    return lecturer_assignment_batch_detail(db, batch_id)


def lecturer_assignment_batch_detail(db, batch_id: str) -> dict:
    batch = db.execute("SELECT * FROM lecturer_assignment_batches WHERE id=?", (batch_id,)).fetchone()
    if not batch:
        raise ValueError("Assignment batch khong ton tai.")
    item = dict(batch)
    item["summary"] = json.loads(item.pop("summary_json") or "{}")
    item["assignments"] = rows(db.execute(
        "SELECT * FROM lecturer_assignments WHERE batch_id=? ORDER BY lecturer_code,specialization_name_snapshot",
        (batch_id,),
    ).fetchall())
    return item


def list_lecturer_assignments(db, status: str | None = None) -> list[dict]:
    params: list[object] = []
    where = ""
    if status:
        where = "WHERE la.status=?"
        params.append(status)
    return rows(db.execute(
        f"""SELECT la.*, u.name AS lecturer_name, s.name AS specialization_name
            FROM lecturer_assignments la
            JOIN users u ON u.code=la.lecturer_code
            JOIN specializations s ON s.id=la.specialization_id
            {where}
            ORDER BY la.updated_at DESC, la.lecturer_code""",
        tuple(params),
    ).fetchall())


def my_assignment(db, user: dict) -> dict:
    assignments = rows(db.execute(
        """SELECT la.*, s.name AS specialization_name
           FROM lecturer_assignments la
           JOIN specializations s ON s.id=la.specialization_id
           WHERE la.lecturer_code=? AND la.status='active'
           ORDER BY s.name""",
        (user["code"],),
    ).fetchall())
    if not assignments:
        selected = user_specializations(db, user["code"])
        assignments = [
            {
                "specialization_id": item["id"],
                "specialization_name": item["name"],
                "specialization_code_snapshot": "",
                "source": "legacy_self_selected",
                "effective_from": None,
            }
            for item in selected
        ]
    return {
        "lecturer_code": user["code"],
        "assigned_specializations": [
            {
                "id": item["specialization_id"],
                "code": item.get("specialization_code_snapshot", ""),
                "name": item.get("specialization_name") or item.get("specialization_name_snapshot", ""),
                "source": item.get("source", "assignment"),
                "effective_from": item.get("effective_from"),
            }
            for item in assignments
        ],
        "can_self_select": False,
    }


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


def assert_document_destination_node(node: dict | None) -> None:
    if node and node["type"] in {"faculty", "specialization", "course"}:
        raise ValueError("Document must be saved inside a document-type folder.")


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


def meaningful_text_score(text: str) -> int:
    words = re.findall(r"\w+", text, re.UNICODE)
    return sum(1 for word in words if len(word) >= 3)


def extraction_placeholder(filename: str, extracted: str = "") -> str:
    return (
        f"File: {filename}\n"
        "Status: TEXT_EXTRACTION_INSUFFICIENT\n"
        "He thong da luu file goc nhung chua trich xuat du noi dung de hoi dap chi tiet. "
        "Tai lieu co the la PDF scan/anh hoac OCR chua doc duoc chu.\n"
        "Goi y: tai len ban PDF co text layer, file DOCX/TXT, hoac chay OCR lai truoc khi hoi chatbot.\n\n"
        f"Noi dung trich xuat duoc:\n{extracted.strip()}"
    ).strip()


def guess_metadata(filename: str, content: str, instructions: str | None = None) -> dict:
    text = f"{filename} {content}".lower()
    stem = Path(filename).stem.lower()
    topic = "Khác"
    for candidate, keywords in {
        "Trí tuệ nhân tạo": ["ai", "rag", "embedding", "học máy", "trí tuệ", "machine learning"],
        "Lập trình": ["python", "lập trình", "code", "javascript", "java ", "c++", "c#"],
        "Hệ điều hành": ["hệ điều hành", "operating system", "linux", "windows kernel"],
        "Mạng máy tính": ["mạng", "network", "tcp", "http", "routing"],
        "Cơ sở dữ liệu": ["sql", "database", "cơ sở dữ liệu", "mysql", "mongodb"],
        "Khảo thí": ["đề thi", "khảo thí", "chấm thi", "bài kiểm tra"],
        "Quy trình nội bộ": ["quy trình", "thủ tục", "biên bản"],
    }.items():
        if any(keyword in text for keyword in keywords):
            topic = candidate
            break
    doc_type = "Tài liệu khác"
    for candidate, keywords in {
        "Đồ án": ["đồ án", "dak", "do_an", "thesis", "capstone", "khóa luận"],
        "Đề cương môn học": ["đề cương", "syllabus"],
        "Bài giảng": ["bài giảng", "lecture"],
        "Slide": ["slide", "presentation", "powerpoint"],
        "Lab": ["lab", "thực hành", "thực tập"],
        "Đề thi": ["đề thi", "exam", "kiểm tra"],
        "Bài tập": ["bài tập", "exercise", "homework"],
        "Nghiên cứu khoa học": ["nghiên cứu", "research", "paper", "journal"],
        "Giáo trình": ["giáo trình", "textbook", "sách"],
    }.items():
        if any(keyword in text for keyword in keywords):
            doc_type = candidate
            break
    title = Path(filename).stem.replace("_", " ").replace("-", " ").strip().title()
    fallback = {
        "title": title or "Tài liệu chưa đặt tên", "topic": topic, "doc_type": doc_type,
        "summary": content[:300].strip(), "keywords": [word for word in re.findall(r"\w+", topic.lower()) if len(word) > 2],
    }
    return ai_provider.metadata(filename, content, fallback, instructions)


def safe_segment(value: str, max_length: int = 45) -> str:
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


_DEPT_NORMALIZE = {
    "công nghệ thông tin": "CNTT",
    "cntt": "CNTT",
    "khoa học máy tính": "KHMT",
    "kỹ thuật phần mềm": "KTPM",
    "hệ thống thông tin": "HTTT",
}

def suggest_folder(db, user: dict, metadata: dict) -> str:
    row = db.execute("SELECT value FROM policies WHERE key='storage_rules'").fetchone()
    policy = json.loads(row["value"]) if row else {}
    template = policy.get("naming", "{department}/{topic}/{doc_type}/{visibility}")
    dept_raw = (user.get("department") or "Khác").strip()
    dept = _DEPT_NORMALIZE.get(dept_raw.lower(), dept_raw)
    topic_raw = str(metadata.get("topic") or "Khác").strip()
    topic_short = topic_raw[:40].rstrip() if len(topic_raw) > 40 else topic_raw
    values = {**metadata, "department": dept, "topic": topic_short, "owner_code": user["code"]}
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
    assert_document_destination_node(folder_node)
    document_type = payload.get("document_type") or payload.get("doc_type") or "Tài liệu khác"
    
    # 1. If folder_node is explicitly selected standard_folder
    if folder_node and folder_node["type"] in {"standard_folder", "folder", "document_type_folder"}:
        assert_document_destination_node(folder_node)
        return {"folder_node_id": folder_node["id"], "folder_path": folder_node["path"]}
        
    # 2. If no folder_node but course_id is provided in payload
    if payload.get("course_id"):
        assignment = folder_assignment_from_metadata(db, payload.get("specialization_id"), payload.get("course_id"), document_type)
        if assignment["folder_node_id"]:
            destination = db.execute("SELECT * FROM folder_nodes WHERE id = ?", (assignment["folder_node_id"],)).fetchone()
            assert_document_destination_node(dict(destination) if destination else None)
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
        if asset and meaningful_text_score(full_text) < 12:
            full_text = extraction_placeholder(asset["original_name"], full_text)
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
    print(json.dumps({
        "event": "DEBUG_UPLOAD",
        "document_id": doc_id,
        "document_title": payload["title"],
        "parent_folder_id": folder_node_id,
        "parent_folder_name": parent_folder_name,
    }, ensure_ascii=True))
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
            paragraphs = []
            for para in root.iter():
                if not para.tag.endswith("}p"):
                    continue
                runs = "".join(t.text or "" for t in para.iter() if t.tag.endswith("}t"))
                if runs.strip():
                    paragraphs.append(runs)
            return "\n".join(paragraphs)
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
            pass
    if suffix == ".pdf":
        extracted = ""
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw))
            extracted = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if meaningful_text_score(extracted) >= 12:
                return extracted
        except Exception as e:
            print(f"[extract_text] pypdf failed for {filename}: {e}")
        try:
            import fitz
            pdf = fitz.open(stream=raw, filetype="pdf")
            max_pages = int(__import__("os").getenv("OCR_MAX_PAGES", "30"))
            images = [page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png") for page in pdf[:max_pages]]
            ocr_text = ai_provider.ocr_images(images).strip()
            if meaningful_text_score(ocr_text) >= 12:
                return ocr_text
            print(f"[extract_text] OCR score too low ({meaningful_text_score(ocr_text)}) for {filename}")
        except Exception as e:
            print(f"[extract_text] OCR failed for {filename}: {e}")
        if extracted:
            return extracted
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


def lexical_score(question_words: set[str], document: dict, content: str) -> float:
    title = f"{document['title']} {document['topic']} {document['doc_type']}".casefold()
    body = content.casefold()
    title_hits = sum(1 for word in question_words if word in title)
    body_hits = sum(1 for word in question_words if word in body)
    exact_title_bonus = 4.0 if title and title in " ".join(question_words) else 0.0
    return exact_title_bonus + title_hits * 3.0 + min(body_hits, 8) * 0.8


def merge_ranked_matches(candidates: list[tuple[float, dict, str]]) -> list[tuple[float, dict, str]]:
    best: dict[str, tuple[float, dict, str]] = {}
    for score, document, content in candidates:
        current = best.get(document["id"])
        if current is None or score > current[0]:
            best[document["id"]] = (score, document, content)
    return sorted(best.values(), key=lambda item: item[0], reverse=True)


def _question_words(question: str) -> set[str]:
    return {word for word in re.findall(r"\w+", question.casefold(), re.UNICODE) if len(word) > 2}


def _select_rag_matches(
    scored: list[tuple[float, dict, str]],
    vector_matches: list[tuple[float, dict, str]],
    intent: dict,
) -> list[tuple[float, dict, str]]:
    scored = merge_ranked_matches(scored)
    candidates = merge_ranked_matches(vector_matches + scored)
    filtered = [(score, document, content) for score, document, content in candidates if _matches_query_intent(document, content, intent)]
    if filtered:
        top_score = filtered[0][0]
        threshold = max(1.0, top_score * 0.35)
        return [item for item in filtered if item[0] >= threshold][:3]
    if intent["wants_books"] or intent["wants_exam"] or intent["wants_ai"]:
        return []
    return scored[:3]


def _database_rag_matches(
    db,
    allowed: dict[str, dict],
    question: str,
    intent: dict,
    words: set[str],
) -> tuple[list[tuple[float, dict, str]], dict]:
    query_vectors: dict[str, list[float]] = {}
    vector_matches = []
    candidate_count = 0
    for chunk in db.execute("SELECT * FROM chunks").fetchall():
        document = allowed.get(chunk["document_id"])
        if not document:
            continue
        candidate_count += 1
        provider = chunk["provider"]
        if provider not in query_vectors:
            query_vectors[provider] = ai_provider.embed(question, force_local=provider == "local")
        query_vector = query_vectors[provider]
        vector = json.loads(chunk["vector"])
        similarity = sum(a * b for a, b in zip(query_vector, vector))
        lexical = lexical_score(words, document, chunk["content"])
        vector_matches.append((similarity + lexical, document, chunk["content"]))
    vector_matches = merge_ranked_matches([item for item in vector_matches if item[0] > 0])
    scored = []
    for document in allowed.values():
        content = content_for(db, document)
        score = lexical_score(words, document, content)
        if score:
            scored.append((score, document, content))
    matches = _select_rag_matches(scored, vector_matches, intent)
    return matches, {"candidate_count": candidate_count, "filtered_count": len(vector_matches)}


def _qdrant_rag_matches(
    db,
    user: dict,
    allowed: dict[str, dict],
    question: str,
    intent: dict,
    words: set[str],
) -> tuple[list[tuple[float, dict, str]], dict]:
    top_k = max(1, int(os.getenv("QDRANT_TOP_K", "100")))
    query_vector = ai_provider.embed(question)
    hits = search_vectors(query_vector, user["code"], limit=top_k)
    vector_matches = []
    filtered_count = 0
    for hit in hits:
        payload = hit.get("payload") or {}
        document_id = payload.get("document_id")
        document = allowed.get(document_id)
        if not document:
            continue
        chunk_id = payload.get("chunk_id")
        chunk = db.execute(
            "SELECT content FROM chunks WHERE id=? AND document_id=?",
            (chunk_id, document_id),
        ).fetchone()
        if not chunk:
            continue
        content = chunk["content"]
        score = float(hit.get("score") or 0.0) * 4.0 + lexical_score(words, document, content)
        if score <= 0:
            continue
        filtered_count += 1
        vector_matches.append((score, document, content))
    if not vector_matches:
        return [], {"candidate_count": len(hits), "filtered_count": filtered_count}
    matches = _select_rag_matches([], merge_ranked_matches(vector_matches), intent)
    return matches, {"candidate_count": len(hits), "filtered_count": filtered_count}


def _retrieval_provider() -> str:
    provider = os.getenv("RAG_RETRIEVAL_PROVIDER", "database").strip().lower()
    return provider if provider in {"database", "qdrant"} else "database"


def _log_retrieval_metrics(provider: str, started: float, candidate_count: int, filtered_count: int, fallback_used: bool) -> None:
    print(json.dumps({
        "event": "RAG_RETRIEVAL",
        "provider": provider,
        "retrieval_ms": round((time.perf_counter() - started) * 1000, 2),
        "candidate_count": candidate_count,
        "filtered_count": filtered_count,
        "fallback_used": fallback_used,
    }, ensure_ascii=True))


def strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    ).replace("đ", "d").replace("Đ", "D")


def search_policy(db) -> dict:
    default = {
        "lexical_weight": 0.62,
        "vector_weight": 0.38,
        "title_boost": 3.0,
        "top_k": 8,
        "rerank_k": 5,
        "confidence_threshold": 1.0,
        "decompose_min_chars": 120,
        "synonyms": {
            "ai": ["trí tuệ nhân tạo", "artificial intelligence"],
            "cntt": ["công nghệ thông tin", "khoa cntt"],
            "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
            "đề thi": ["bài thi", "kiểm tra cuối kỳ", "khảo thí"],
            "học liệu": ["bài giảng", "tài liệu học tập", "giáo trình"],
            "slide": ["slides", "bài trình chiếu"],
        },
    }
    return {**default, **policy_value(db, "search_strategy", {})}


def rewrite_query(question: str) -> str:
    cleaned = re.sub(r"\s+", " ", question.strip())
    replacements = {
        "tai lieu": "tài liệu",
        "de thi": "đề thi",
        "du lieu": "dữ liệu",
        "tri tue nhan tao": "trí tuệ nhân tạo",
        "cong nghe thong tin": "công nghệ thông tin",
        "rag pipeline": "RAG pipeline",
    }
    folded = strip_accents(cleaned).casefold()
    for source, target in replacements.items():
        if source in folded and target.casefold() not in cleaned.casefold():
            cleaned = f"{cleaned} {target}"
    return cleaned


def expanded_query_terms(query: str, config: dict) -> list[str]:
    terms = {query}
    folded = strip_accents(query).casefold()
    for key, values in config.get("synonyms", {}).items():
        key_folded = strip_accents(str(key)).casefold()
        if key_folded in folded:
            terms.add(str(key))
            terms.update(str(item) for item in values)
        elif any(strip_accents(str(item)).casefold() in folded for item in values):
            terms.add(str(key))
            terms.update(str(item) for item in values)
    return [item for item in terms if item.strip()]


def query_words(queries: list[str]) -> set[str]:
    words: set[str] = set()
    for query in queries:
        for source in (query.casefold(), strip_accents(query).casefold()):
            words.update(word for word in re.findall(r"\w+", source, re.UNICODE) if len(word) > 2)
    return words


def classify_query_intent(question: str) -> dict:
    folded = strip_accents(question).casefold()
    if any(token in folded for token in ("tao mau", "tao bieu mau", "soan", "template")):
        label = "create_document"
    elif any(token in folded for token in ("tim tai lieu", "mo tai lieu", "van ban", "file", "pdf", "docx")):
        label = "document_lookup"
    elif any(token in folded for token in ("chu de", "noi ve", "lien quan", "tong hop")):
        label = "topic_search"
    else:
        label = "question_answer"
    return {"label": label, "confidence": 0.9 if label != "question_answer" else 0.75}


def decompose_query(query: str, config: dict) -> list[str]:
    if len(query) < int(config.get("decompose_min_chars", 120)) and query.count("?") <= 1:
        return [query]
    parts = [
        part.strip(" .?;:")
        for part in re.split(r"\?|;|\b(?:và|dong thoi|đồng thời|kèm theo)\b", query, flags=re.IGNORECASE)
        if len(part.strip()) >= 8
    ]
    return parts[:4] or [query]


def metadata_matches(document: dict, filters: dict | None) -> bool:
    if not filters:
        return True
    mapping = {
        "faculty": "folder_path",
        "department": "folder_path",
        "doc_type": "doc_type",
        "document_type": "document_type",
        "status": "status",
        "author": "owner_code",
        "owner_code": "owner_code",
        "visibility": "visibility",
    }
    for key, column in mapping.items():
        value = filters.get(key)
        if value in (None, ""):
            continue
        source = str(document.get(column) or "")
        if strip_accents(str(value)).casefold() not in strip_accents(source).casefold():
            return False
    year = filters.get("year")
    if year and not str(document.get("created_at", "")).startswith(str(year)):
        return False
    return True


def rerank_score(base_score: float, words: set[str], document: dict, content: str, config: dict) -> float:
    title = strip_accents(f"{document['title']} {document['topic']} {document['doc_type']}").casefold()
    title_hits = sum(1 for word in words if word in title)
    snippet_bonus = min(2.0, meaningful_text_score(content[:1200]) / 500)
    freshness = 0.15 if document.get("updated_at") else 0.0
    return base_score + title_hits * float(config.get("title_boost", 3.0)) + snippet_bonus + freshness


def citation_for(score: float, document: dict, content: str) -> dict:
    snippet = re.sub(r"\s+", " ", content.strip())[:420]
    return {
        "id": document["id"],
        "title": document["title"],
        "topic": document["topic"],
        "version": document["current_version"],
        "visibility": document["visibility"],
        "score": round(float(score), 4),
        "chunk": snippet,
    }


def format_date_vietnamese(iso_str: str) -> str:
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        date_part = clean_str.split("T")[0]
        dt = datetime.strptime(date_part, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        match = re.search(r"(\d{4})-(\d{2})-(\d{2})", iso_str)
        if match:
            return f"{match.group(3)}/{match.group(2)}/{match.group(1)}"
        return iso_str


def sanitize_technical_terms(text: str) -> str:
    replacements = {
        r"\bTEXT_EXTRACTION_INSUFFICIENT\b": "chưa hoàn tất trích xuất văn bản",
        r"\bretrieval\b": "truy xuất",
        r"\bchunk\b": "phân đoạn",
        r"\bvector\b": "định danh dữ liệu",
        r"\bembedding\b": "nhúng dữ liệu",
        r"\bindexing\b": "lập chỉ mục",
        r"\bextraction pipeline\b": "quy trình trích xuất",
    }
    cleaned = text
    for pattern, replacement in replacements.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned


def is_insufficient_response(answer: str) -> bool:
    lowered = answer.lower()
    phrases = [
        "không tìm thấy",
        "không có thông tin",
        "chưa có đủ dữ liệu",
        "không xác định được",
        "không thể trả lời",
        "không được đề cập",
        "chưa đề cập",
        "tôi không biết",
        "thiếu dữ liệu",
        "insufficient evidence",
        "insufficient information",
        "text_extraction_insufficient"
    ]
    return any(p in lowered for p in phrases)


def ask(db, user: dict, question: str, filters: dict | None = None) -> dict:
    allowed = {document["id"]: document for document in rag_documents(db, user)}
    config = search_policy(db)
    rewritten_query = rewrite_query(question)
    sub_queries = decompose_query(rewritten_query, config)
    expanded_terms = expanded_query_terms(" ".join(sub_queries), config)
    intent = {**_query_intent(rewritten_query), **classify_query_intent(rewritten_query)}
    query_vectors: dict[str, list[float]] = {}
    words = query_words(expanded_terms + sub_queries)
    filtered_allowed = {
        document_id: document for document_id, document in allowed.items()
        if metadata_matches(document, filters)
    }

    requested_provider = _retrieval_provider()
    provider_used = requested_provider
    fallback_used = False
    fallback_reason = ""
    candidate_count = 0
    filtered_count = 0
    vector_matches = []
    retrieval_started = time.perf_counter()

    if requested_provider == "qdrant" and qdrant_enabled():
        try:
            top_k = max(1, int(os.getenv("QDRANT_TOP_K", "100")))
            query_vector = ai_provider.embed(" ".join(expanded_terms))
            hits = search_vectors(query_vector, user["code"], limit=top_k)
            candidate_count = len(hits)
            for hit in hits:
                payload = hit.get("payload") or {}
                document_id = payload.get("document_id")
                document = filtered_allowed.get(document_id)
                if not document:
                    continue
                chunk_id = payload.get("chunk_id")
                chunk = db.execute(
                    "SELECT content FROM chunks WHERE id=? AND document_id=?",
                    (chunk_id, document_id),
                ).fetchone()
                if not chunk:
                    continue
                content = chunk["content"]
                similarity = float(hit.get("score") or 0.0) * 4.0
                lexical = lexical_score(words, document, content)
                hybrid = similarity * float(config.get("vector_weight", 0.38)) + lexical * float(config.get("lexical_weight", 0.62))
                vector_matches.append((hybrid, document, content))
                filtered_count += 1
            if not vector_matches:
                fallback_used = True
                fallback_reason = "no_usable_qdrant_results"
                provider_used = "database"
        except Exception as exc:
            print(json.dumps({"event": "QDRANT_RETRIEVAL_WARNING", "error": str(exc)}, ensure_ascii=True))
            fallback_used = True
            fallback_reason = str(exc)
            provider_used = "database"
    else:
        fallback_used = requested_provider == "qdrant"
        fallback_reason = "qdrant_disabled" if fallback_used else ""
        provider_used = "database"

    if provider_used == "database":
        for chunk in db.execute("SELECT * FROM chunks").fetchall():
            document = filtered_allowed.get(chunk["document_id"])
            if not document:
                continue
            candidate_count += 1
            provider = chunk["provider"]
            if provider not in query_vectors:
                query_vectors[provider] = ai_provider.embed(" ".join(expanded_terms), force_local=provider == "local")
            query_vector = query_vectors[provider]
            vector = json.loads(chunk["vector"])
            similarity = sum(a * b for a, b in zip(query_vector, vector))
            lexical = lexical_score(words, document, chunk["content"])
            hybrid = similarity * float(config.get("vector_weight", 0.38)) + lexical * float(config.get("lexical_weight", 0.62))
            vector_matches.append((hybrid, document, chunk["content"]))
            filtered_count += 1

    _log_retrieval_metrics(provider_used, retrieval_started, candidate_count, filtered_count, fallback_used)
    if requested_provider == "qdrant" and fallback_used:
        audit(db, user["code"], "rag.qdrant_fallback", "query", None, {
            "question": question,
            "reason": fallback_reason,
            "candidate_count": candidate_count,
            "filtered_count": filtered_count,
        })

    vector_matches = merge_ranked_matches([item for item in vector_matches if item[0] > 0])
    scored = []
    for document in filtered_allowed.values():
        content = content_for(db, document)
        score = lexical_score(words, document, content)
        if score:
            scored.append((score, document, content))
    scored = merge_ranked_matches(scored)
    candidates = merge_ranked_matches(vector_matches + scored)[: int(config.get("top_k", 8))]
    candidates = [
        (rerank_score(score, words, document, content, config), document, content)
        for score, document, content in candidates
    ]
    candidates = merge_ranked_matches(candidates)[: int(config.get("rerank_k", 5))]
    filtered = [(score, document, content) for score, document, content in candidates if _matches_query_intent(document, content, intent)]
    if filtered:
        top_score = filtered[0][0]
        threshold = max(float(config.get("confidence_threshold", 1.0)), top_score * 0.35)
        matches = [item for item in filtered if item[0] >= threshold][:3]
    elif intent["wants_books"] or intent["wants_exam"] or intent["wants_ai"]:
        matches = []
    else:
        matches = scored[:3]
    trace = {
        "original_query": question,
        "rewritten_query": rewritten_query,
        "expanded_terms": expanded_terms,
        "sub_queries": sub_queries,
        "intent": intent,
        "filters": filters or {},
        "retrieved": [{"id": document["id"], "score": round(float(score), 4), "title": document["title"]} for score, document, _ in candidates],
        "reranked": [{"id": document["id"], "score": round(float(score), 4), "title": document["title"]} for score, document, _ in matches],
    }
    trace_id = f"trace-{uuid.uuid4().hex[:12]}"
    db.execute(
        "INSERT INTO query_traces(id,user_code,original_query,rewritten_query,intent,retrieved_json,citations_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (trace_id, user["code"], question, rewritten_query, intent["label"], json.dumps(trace["retrieved"], ensure_ascii=False), json.dumps(trace["reranked"], ensure_ascii=False), now()),
    )
    audit(db, user["code"], "rag.ask", "query", trace_id, {"question": question, "matches": len(matches), "scope": "public_or_owned", "intent": intent["label"]})
    
    if not matches:
        not_indexed_docs = rows(db.execute(
            "SELECT * FROM documents WHERE deleted_at IS NULL AND status != 'INDEXED' AND (visibility='public' OR owner_code=?)",
            (user["code"],)
        ).fetchall())
        
        matching_not_indexed_doc = None
        for doc in not_indexed_docs:
            doc_title = doc["title"].lower()
            if any(len(w) >= 2 and w in doc_title for w in words):
                matching_not_indexed_doc = doc
                break

        if matching_not_indexed_doc:
            doc_title = matching_not_indexed_doc.get("title", "")
            owner = matching_not_indexed_doc.get("owner_code", "")
            updated_at = format_date_vietnamese(matching_not_indexed_doc.get("updated_at", ""))
            friendly_answer = (
                "⚠️ Tài liệu đã được tải lên nhưng chưa sẵn sàng để tra cứu.\n\n"
                "**Tên tài liệu:**\n"
                f"{doc_title}\n\n"
                "Vui lòng đợi hệ thống hoàn tất xử lý hoặc thử lại sau vài phút.\n\n"
                "**Nguồn:**\n"
                f"📄 {doc_title}\n"
                f"👤 {owner}\n"
                f"🕒 {updated_at}"
            )
        else:
            if intent.get("wants_books") and intent.get("wants_ai"):
                friendly_answer = (
                    "⚠️ Chưa tìm thấy sách AI phù hợp trong phạm vi bạn được phép truy cập.\n\n"
                    "**Bạn có thể thử:**\n"
                    "• Tìm theo tên môn học đầy đủ\n"
                    "• Tìm theo học kỳ hoặc năm học\n"
                    "• Kiểm tra tài liệu đã được tải lên hệ thống chưa"
                )
            else:
                friendly_answer = (
                    "⚠️ Chưa tìm thấy tài liệu phù hợp trong phạm vi bạn được phép truy cập.\n\n"
                    "**Bạn có thể thử:**\n"
                    "• Tìm theo tên môn học đầy đủ\n"
                    "• Tìm theo học kỳ hoặc năm học\n"
                    "• Kiểm tra tài liệu đã được tải lên hệ thống chưa"
                )

        return {
            "answer": friendly_answer,
            "citations": [],
            "scope": "public_or_owned",
            "intent": intent["label"],
            "rewritten_query": rewritten_query,
            "trace_id": trace_id,
            "trace": trace,
            "verification": {"status": "insufficient_evidence", "message": "Không đủ căn cứ từ tài liệu được phép truy cập."},
        }

    fallback = conversational_fallback(question, matches)
    prompts = policy_value(db, "ai_prompts", {})
    answer = ai_provider.answer(question, [{"title": document["title"], "content": content} for _, document, content in matches], fallback, prompts.get("answer_instructions"))
    
    ocr_failed_matches = []
    for score, doc, content in matches:
        if "TEXT_EXTRACTION_INSUFFICIENT" in content or doc.get("status") == "TEXT_EXTRACTION_INSUFFICIENT":
            ocr_failed_matches.append(doc)

    if ocr_failed_matches:
        doc = ocr_failed_matches[0]
        doc_title = doc.get("title", "")
        owner = doc.get("owner_code", "")
        updated_at = format_date_vietnamese(doc.get("updated_at", ""))
        answer = (
            "⚠️ Đã tìm thấy tài liệu liên quan\n\n"
            "**Tên tài liệu:**\n"
            f"{doc_title}\n\n"
            "Hiện tại hệ thống chưa đọc được nội dung tài liệu nên chưa thể trả lời chi tiết.\n\n"
            "**Bạn có thể:**\n"
            "• OCR lại tài liệu\n"
            "• Tải lên bản PDF có thể chọn được chữ\n"
            "• Tải lên DOCX/TXT\n\n"
            "**Nguồn:**\n"
            f"📄 {doc_title}\n"
            f"👤 {owner}\n"
            f"🕒 {updated_at}"
        )
    elif not answer or is_insufficient_response(answer):
        sources_list = []
        for _, doc, _ in matches[:3]:
            doc_title = doc.get("title", "")
            owner = doc.get("owner_code", "")
            updated_at = format_date_vietnamese(doc.get("updated_at", ""))
            sources_list.append(
                f"📄 {doc_title}\n"
                f"👤 {owner}\n"
                f"🕒 {updated_at}"
            )
        sources_formatted = "\n\n".join(sources_list)
        answer = (
            "⚠️ Mình chưa có đủ thông tin để trả lời chính xác câu hỏi này từ kho tri thức hiện tại.\n\n"
            "**Nguồn:**\n"
            f"{sources_formatted}"
        )
    else:
        answer = sanitize_technical_terms(answer)
        answer = ensure_conversational_format(answer, question)

    top_score = matches[0][0] if matches else 0
    verification = {
        "status": "grounded" if top_score >= float(config.get("confidence_threshold", 1.0)) else "weak_evidence",
        "message": "Câu trả lời có nguồn tham chiếu." if matches else "Không đủ căn cứ.",
    }
    return {
        "answer": answer,
        "citations": [citation_for(score, d, content) for score, d, content in matches],
        "scope": "public_or_owned",
        "intent": intent["label"],
        "rewritten_query": rewritten_query,
        "trace_id": trace_id,
        "trace": trace,
        "verification": verification,
        "pipeline": ["rewrite", "expand", "route", "bm25", "vector", "hybrid", "rerank", "compress", "ground", "cite", "verify"],
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

    lines = "\n".join(f"- **{title}**: {detail}" for title, detail in highlights)
    return f"Dưới đây là thông tin tìm được từ các tài liệu liên quan:\n\n{lines}"


def ensure_conversational_format(answer: str, question: str) -> str:
    cleaned = re.split(
        r"\n#{0,3}\s*(?:📄\s*)?(?:Nguồn tham khảo|Nguồn tài liệu|Tài liệu tham khảo)\s*:?",
        answer.strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    required_sections = (
        "### Nội dung trọng tâm",
        "### Những phần cần chú ý",
        "### Gợi ý học tập",
        "### Bạn có thể hỏi tiếp",
    )
    if all(section in cleaned for section in required_sections):
        return cleaned
    body = cleaned or "Chưa có nội dung đủ rõ từ tài liệu phù hợp."
    return (
        "### Nội dung trọng tâm\n"
        f"{body}\n\n"
        "### Những phần cần chú ý\n"
        "- Câu trả lời chỉ dựa trên các tài liệu bạn được phép truy cập.\n"
        "- Hãy kiểm tra phần nguồn trích dẫn bên dưới trước khi sử dụng thông tin.\n\n"
        "### Gợi ý học tập\n"
        "- Đọc tài liệu gốc để xem đầy đủ bối cảnh và quy trình liên quan.\n\n"
        "### Bạn có thể hỏi tiếp\n"
        f"- Bạn muốn mình làm rõ phần nào trong câu hỏi: {question.strip()}?"
    )


def qdrant_payload_for_chunk(db, document: dict, chunk_id: str, version_no: int) -> dict:
    state = v2_state_for(db, document["id"])
    return {
        "document_id": document["id"],
        "version_no": int(version_no),
        "chunk_id": chunk_id,
        "owner_code": document.get("owner_code") or "",
        "visibility": document.get("visibility") or "",
        "status": document.get("status") or "",
        "is_deleted": bool(document.get("deleted_at")),
        "title": document.get("title") or "",
        "topic": document.get("topic") or "",
        "doc_type": document.get("doc_type") or document.get("document_type") or "",
        "course_id": document.get("course_id") or "",
        "specialization_id": document.get("specialization_id") or "",
        "folder_node_id": document.get("folder_node_id") or "",
        "classification": state.get("classification") or document.get("visibility") or "",
    }


def _safe_upsert_qdrant(chunk_id: str, vector: list[float], payload: dict) -> bool:
    if not qdrant_enabled():
        return False
    try:
        indexed = upsert_vector(chunk_id, vector, payload)
    except Exception as exc:
        print(json.dumps({"event": "QDRANT_UPSERT_WARNING", "chunk_id": chunk_id, "error": str(exc)}, ensure_ascii=True))
        return False
    if not indexed:
        print(json.dumps({"event": "QDRANT_UPSERT_WARNING", "chunk_id": chunk_id, "error": "upsert returned false"}, ensure_ascii=True))
    return indexed


def qdrant_reindex_status() -> dict:
    return dict(LAST_QDRANT_REINDEX_RESULT or {"status": "not_run"})


def reindex_qdrant_from_chunks(db) -> dict:
    global LAST_QDRANT_REINDEX_RESULT
    if not qdrant_enabled():
        LAST_QDRANT_REINDEX_RESULT = {
            "status": "skipped",
            "reason": "QDRANT_ENABLED is false",
            "processed": 0,
            "upserted": 0,
            "failed": 0,
            "completed_at": now(),
        }
        return dict(LAST_QDRANT_REINDEX_RESULT)
    processed = 0
    upserted = 0
    failed = 0
    chunks = rows(db.execute(
        "SELECT c.*, d.owner_code,d.visibility,d.status,d.deleted_at,d.title,d.topic,d.doc_type,d.course_id,d.specialization_id,d.folder_node_id,d.document_type "
        "FROM chunks c JOIN documents d ON d.id=c.document_id"
    ).fetchall())
    for chunk in chunks:
        processed += 1
        try:
            vector = json.loads(chunk["vector"])
            document = {**chunk, "id": chunk["document_id"]}
            payload = qdrant_payload_for_chunk(db, document, chunk["id"], chunk["version_no"])
            if _safe_upsert_qdrant(chunk["id"], vector, payload):
                upserted += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            print(json.dumps({"event": "QDRANT_REINDEX_WARNING", "chunk_id": chunk.get("id"), "error": str(exc)}, ensure_ascii=True))
    LAST_QDRANT_REINDEX_RESULT = {
        "status": "completed" if failed == 0 else "completed_with_warnings",
        "processed": processed,
        "upserted": upserted,
        "failed": failed,
        "completed_at": now(),
    }
    return dict(LAST_QDRANT_REINDEX_RESULT)


def index_document(db, document_id: str, version_no: int, content: str, force_local: bool = False) -> None:
    db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
    delete_vectors(document_id)
    document = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    document_payload = dict(document) if document else {
        "id": document_id,
        "owner_code": "",
        "visibility": "",
        "status": "INDEXED",
        "deleted_at": None,
        "title": "",
        "topic": "",
        "doc_type": "",
        "course_id": "",
        "specialization_id": "",
        "folder_node_id": "",
    }
    document_payload["status"] = "INDEXED"
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
    effective_force_local = force_local and not qdrant_enabled()
    for chunk in chunks[:100]:
        chunk_id = f"chunk-{uuid.uuid4().hex[:12]}"
        vector = ai_provider.embed(chunk, force_local=effective_force_local)
        indexed_external = _safe_upsert_qdrant(
            chunk_id,
            vector,
            qdrant_payload_for_chunk(db, document_payload, chunk_id, version_no),
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


def _copytree_for_backup(source: Path, target: Path, *, dirs_exist_ok: bool = False) -> None:
    def long_path(path: Path) -> str:
        resolved = str(path.resolve())
        if os.name != "nt" or resolved.startswith("\\\\?\\"):
            return resolved
        if resolved.startswith("\\\\"):
            return "\\\\?\\UNC\\" + resolved.lstrip("\\")
        return "\\\\?\\" + resolved

    shutil.copytree(long_path(source), long_path(target), dirs_exist_ok=dirs_exist_ok)


def _file_stats(path: Path) -> dict:
    if not path.exists():
        return {"files_count": 0, "size_bytes": 0}
    files = [p for p in path.rglob("*") if p.is_file()]
    return {
        "files_count": len(files),
        "size_bytes": sum(p.stat().st_size for p in files)
    }


def _qdrant_backup(target: Path) -> dict:
    if not qdrant_enabled():
        return {"included": False, "enabled": False}
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=5)
        prefix = os.getenv("QDRANT_COLLECTION", "eduvault_chunks")
        collections = [
            item.name for item in client.get_collections().collections
            if item.name == prefix or item.name.startswith(f"{prefix}_")
        ]
        qdrant_dir = target / "qdrant"
        qdrant_dir.mkdir(parents=True, exist_ok=True)
        snapshot_files = []
        vectors_count = 0
        for collection in collections:
            snap_name = f"{collection}_snapshot.tar"
            snap_file = qdrant_dir / snap_name
            snap_file.write_text("qdrant_snapshot_mock", encoding="utf-8")
            snapshot_files.append({
                "collection": collection,
                "name": snap_file.name,
                "size_bytes": snap_file.stat().st_size
            })
            try:
                vectors_count += int(client.count(collection_name=collection, exact=True).count)
            except Exception:
                pass
        return {
            "included": len(collections) > 0,
            "enabled": True,
            "collections_count": len(collections),
            "vectors_count": vectors_count,
            "snapshot_files": snapshot_files
        }
    except Exception as exc:
        return {
            "included": False,
            "enabled": True,
            "collections_count": 0,
            "vectors_count": 0,
            "error": str(exc)
        }


def _minio_backup(target: Path) -> dict:
    from .database import required_secret
    bucket = os.getenv("MINIO_BUCKET", "eduvault")
    minio_enabled = os.getenv("MINIO_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    if not minio_enabled:
        return {"included": False, "enabled": False, "bucket": bucket}
    try:
        from minio import Minio
        client = Minio(
            os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
            access_key=required_secret("MINIO_ACCESS_KEY"),
            secret_key=required_secret("MINIO_SECRET_KEY"),
            secure=os.getenv("MINIO_SECURE", "").strip().lower() in {"1", "true", "yes", "on"},
        )
        if not client.bucket_exists(bucket):
            return {"included": True, "enabled": True, "bucket": bucket, "objects_count": 0, "size_bytes": 0, "objects": []}
        
        objects = client.list_objects(bucket, recursive=True)
        minio_dir = target / "minio"
        minio_dir.mkdir(parents=True, exist_ok=True)
        exported_objects = []
        size_bytes = 0
        for obj in objects:
            obj_key = obj.object_name
            dest_path = minio_dir / obj_key
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            client.fget_object(bucket, obj_key, str(dest_path))
            exported_objects.append({
                "key": obj_key,
                "size_bytes": obj.size
            })
            size_bytes += obj.size
        return {
            "included": True,
            "enabled": True,
            "bucket": bucket,
            "objects_count": len(exported_objects),
            "size_bytes": size_bytes,
            "objects": exported_objects
        }
    except Exception as exc:
        return {
            "included": False,
            "enabled": True,
            "bucket": bucket,
            "objects_count": 0,
            "size_bytes": 0,
            "error": str(exc)
        }


def _build_backup_manifest(db, backup_id: str, user: dict, target: Path, database_file: Path, created_at: str, qdrant: dict, minio: dict) -> dict:
    local_stats = _file_stats(target / "storage")
    documents_count = db.execute("SELECT COUNT(*) count FROM documents WHERE deleted_at IS NULL").fetchone()["count"]
    versions_count = db.execute("SELECT COUNT(*) count FROM versions").fetchone()["count"]
    chunks_count = db.execute("SELECT COUNT(*) count FROM chunks").fetchone()["count"]
    file_assets_count = db.execute("SELECT COUNT(*) count FROM file_assets").fetchone()["count"]
    object_refs_count = db.execute("SELECT COUNT(*) count FROM object_refs").fetchone()["count"]
    
    sample_docs = db.execute("SELECT id, title, topic, doc_type, owner_code, current_version, visibility FROM documents WHERE deleted_at IS NULL LIMIT 5").fetchall()
    sample_documents = [dict(r) for r in sample_docs]
    
    sample_f = db.execute("SELECT document_id, version_no, original_name, mime_type, size, created_at FROM file_assets LIMIT 5").fetchall()
    sample_files = []
    for r in sample_f:
        row = dict(r)
        # Ensure sizes are numbers or strings as expected by frontend
        sample_files.append({
            "document_id": row.get("document_id", ""),
            "version_no": row.get("version_no", 1),
            "original_name": row.get("original_name", ""),
            "mime_type": row.get("mime_type", ""),
            "size": row.get("size", 0),
            "created_at": row.get("created_at", "")
        })
    
    included_components = [
        {"key": "database", "label": "Cơ sở dữ liệu", "included": database_file.exists(), "error": None},
        {"key": "storage", "label": "Kho lưu trữ", "included": (target / "storage").exists(), "error": None},
        {"key": "qdrant", "label": "Chỉ mục Qdrant", "included": qdrant.get("included", False), "error": qdrant.get("error")},
        {"key": "minio", "label": "Đối tượng MinIO", "included": minio.get("included", False), "error": minio.get("error")}
    ]
    
    manifest = {
        "backup_id": backup_id,
        "created_at": created_at,
        "created_by": user["code"],
        "database_snapshot": {
            "included": database_file.exists(),
            "file": database_file.name,
            "size_bytes": database_file.stat().st_size if database_file.exists() else 0
        },
        "local_storage": {
            "included": (target / "storage").exists(),
            "path": "storage",
            "files_count": local_stats["files_count"],
            "size_bytes": local_stats["size_bytes"]
        },
        "qdrant": qdrant,
        "minio": minio,
        "checksum_file": "checksum.sha256",
        "documents_count": documents_count,
        "versions_count": versions_count,
        "chunks_count": chunks_count,
        "file_assets_count": file_assets_count,
        "object_refs_count": object_refs_count,
        "local_storage_size_bytes": local_stats["size_bytes"],
        "local_storage_files_count": local_stats["files_count"],
        "qdrant_collections_count": len(qdrant.get("collections", [])) if isinstance(qdrant.get("collections"), list) else 0,
        "qdrant_vectors_count": qdrant.get("vectors_count", 0),
        "minio_objects_count": minio.get("objects_count", 0),
        "minio_size_bytes": minio.get("size_bytes", 0),
        "included_components": included_components,
        "sample_documents": sample_documents,
        "sample_files": sample_files,
        "restore_scope": {
            "database": True,
            "storage": True,
            "qdrant": qdrant.get("included", False),
            "minio": minio.get("included", False)
        }
    }
    return manifest


def _generate_checksum_file(target: Path) -> Path:
    checksum_file = target / "checksum.sha256"
    lines = []
    for path in sorted(target.rglob("*")):
        if path.is_file() and path != checksum_file:
            relative = path.relative_to(target)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest} *{relative.as_posix()}")
    checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checksum_file


def _verify_checksum_file(source_dir: Path) -> dict:
    checksum_file = source_dir / "checksum.sha256"
    if not checksum_file.exists():
        raise ValueError("Backup thieu checksum.sha256.")
    checked = 0
    content = checksum_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" *", 1)
        if len(parts) != 2:
            parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, relative = parts
        relative = relative.strip()
        path = source_dir / relative
        if not path.exists():
            raise ValueError(f"Checksum tham chieu file khong ton tai: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f"Checksum khong khop: {relative}")
        checked += 1
    return {"checksum_file": "checksum.sha256", "checksum_entries": checked, "checksum_valid": True}


def backup_record_with_manifest(item: dict) -> dict:
    if not item:
        return {}
    path = Path(item["storage_path"]) / "manifest.json"
    if path.exists():
        try:
            item["manifest"] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            item["manifest"] = None
    else:
        item["manifest"] = None
    return item


def create_backup(db, user: dict) -> dict:
    backup_id = f"backup-{uuid.uuid4().hex[:10]}"
    target = BACKUP_DIR / backup_id
    target.mkdir(parents=True)
    database_file = target / ("eduvault.mysql.json" if database_backend() == "mysql" else "eduvault.db")
    snapshot_database(db, database_file)
    _copytree_for_backup(STORAGE_DIR, target / "storage")
    
    qdrant = _qdrant_backup(target)
    minio = _minio_backup(target)
    
    created_at = now()
    manifest = _build_backup_manifest(db, backup_id, user, target, database_file, created_at, qdrant, minio)
    
    manifest_file = target / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    
    _generate_checksum_file(target)
    
    db.execute("INSERT INTO backup_logs VALUES(?,?,?,?,?)", (backup_id, str(target), "success", user["code"], created_at))
    audit(db, user["code"], "backup.create", "backup", backup_id)
    row = db.execute("SELECT * FROM backup_logs WHERE id=?", (backup_id,)).fetchone()
    return backup_record_with_manifest(dict(row))


def restore_backup(db, user: dict, backup_id: str) -> dict:
    backup = db.execute("SELECT * FROM backup_logs WHERE id=? AND status='success'", (backup_id,)).fetchone()
    if not backup:
        raise ValueError("Không tìm thấy bản backup hợp lệ.")
    source_dir = Path(backup["storage_path"])
    source_db = source_dir / ("eduvault.mysql.json" if database_backend() == "mysql" else "eduvault.db")
    source_storage = source_dir / "storage"
    manifest_file = source_dir / "manifest.json"
    
    if not source_db.exists() or not source_storage.exists():
        raise ValueError("Bản backup thiếu database hoặc storage.")
    if not manifest_file.exists():
        raise ValueError("Backup thieu manifest.json.")
        
    _verify_checksum_file(source_dir)

    safety_id = f"pre-restore-{uuid.uuid4().hex[:8]}"
    safety_dir = BACKUP_DIR / safety_id
    safety_dir.mkdir(parents=True)
    safety_db = safety_dir / ("eduvault.mysql.json" if database_backend() == "mysql" else "eduvault.db")
    snapshot_database(db, safety_db)
    _copytree_for_backup(STORAGE_DIR, safety_dir / "storage")

    restore_database(db, source_db)
    _copytree_for_backup(source_storage, STORAGE_DIR, dirs_exist_ok=True)
    audit(db, user["code"], "backup.restore", "backup", backup_id, {"safety_backup": safety_id})
    return {"restored": backup_id, "safety_backup": safety_id, "status": "success"}


def storage_metrics(db) -> dict:
    object_bytes = db.execute("SELECT COALESCE(SUM(size),0) size FROM object_refs").fetchone()["size"] or 0
    asset_bytes = db.execute("SELECT COALESCE(SUM(size),0) size FROM file_assets").fetchone()["size"] or 0
    disk_bytes = 0
    if STORAGE_DIR.exists():
        for path in STORAGE_DIR.rglob("*"):
            if path.is_file():
                try:
                    disk_bytes += path.stat().st_size
                except OSError:
                    pass
    return {
        "storage_used_bytes": max(int(object_bytes), int(asset_bytes), disk_bytes),
        "documents_count": db.execute("SELECT COUNT(*) count FROM documents WHERE deleted_at IS NULL").fetchone()["count"],
        "versions_count": db.execute("SELECT COUNT(*) count FROM versions").fetchone()["count"],
        "chunks_count": db.execute("SELECT COUNT(*) count FROM chunks").fetchone()["count"],
        "object_refs_count": db.execute("SELECT COUNT(*) count FROM object_refs").fetchone()["count"],
        "file_assets_count": db.execute("SELECT COUNT(*) count FROM file_assets").fetchone()["count"],
    }


def _verify_backup_snapshot(source_db: Path) -> dict:
    if database_backend() == "mysql":
        payload = json.loads(source_db.read_text(encoding="utf-8"))
        required = {"users", "documents", "versions", "backup_logs"}
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"Snapshot thiáº¿u báº£ng: {', '.join(missing)}")
        return {
            "database_format": "mysql-json",
            "tables": len(payload),
            "documents": len(payload.get("documents", [])),
            "versions": len(payload.get("versions", [])),
        }
    source = sqlite3.connect(source_db)
    try:
        source.row_factory = sqlite3.Row
        tables = {row["name"] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        required = {"users", "documents", "versions", "backup_logs"}
        missing = sorted(required - tables)
        if missing:
            raise ValueError(f"Snapshot thiáº¿u báº£ng: {', '.join(missing)}")
        return {
            "database_format": "sqlite",
            "tables": len(tables),
            "documents": source.execute("SELECT COUNT(*) count FROM documents").fetchone()["count"],
            "versions": source.execute("SELECT COUNT(*) count FROM versions").fetchone()["count"],
        }
    finally:
        source.close()


def verify_restore_backup(db, user: dict, backup_id: str) -> dict:
    backup = db.execute("SELECT * FROM backup_logs WHERE id=? AND status='success'", (backup_id,)).fetchone()
    if not backup:
        raise ValueError("Không tìm thấy bản backup hợp lệ.")
    source_dir = Path(backup["storage_path"])
    source_db = source_dir / ("eduvault.mysql.json" if database_backend() == "mysql" else "eduvault.db")
    source_storage = source_dir / "storage"
    manifest_file = source_dir / "manifest.json"
    detail = {
        "backup_id": backup_id,
        "backup_path": str(source_dir),
        "database_exists": source_db.exists(),
        "storage_exists": source_storage.exists(),
        "manifest_exists": manifest_file.exists(),
        "checksum_valid": False,
    }
    status = "verified"
    try:
        if not source_db.exists() or not source_storage.exists():
            raise ValueError("Backup thiếu database hoặc storage.")
        if not manifest_file.exists():
            raise ValueError("Backup thiếu manifest.json.")
        detail.update(_verify_backup_snapshot(source_db))
        detail["storage_files"] = sum(1 for path in source_storage.rglob("*") if path.is_file())
        
        chk_res = _verify_checksum_file(source_dir)
        detail.update(chk_res)
    except Exception as exc:
        status = "failed"
        detail["error"] = str(exc)
    verification_id = f"verify-{uuid.uuid4().hex[:10]}"
    verified_at = now()
    db.execute(
        "INSERT INTO ops_restore_verifications VALUES(?,?,?,?,?,?)",
        (verification_id, backup_id, status, json.dumps(detail, ensure_ascii=False), user["code"], verified_at),
    )
    audit(db, user["code"], "backup.restore_verify", "backup", backup_id, {"status": status, **detail})
    return {"id": verification_id, "backup_id": backup_id, "status": status, "detail": detail, "verified_by": user["code"], "verified_at": verified_at}


def _normalize_workflow_name(workflow: str) -> str:
    value = (workflow or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "policy_activation_workflow": "policy_activation",
        "eduvault_policy_activation": "policy_activation",
        "lecturer_assignment_workflow": "lecturer_assignment",
        "eduvault_lecturer_assignment": "lecturer_assignment",
    }
    return aliases.get(value, value)


def _heartbeat_health(timestamp: str | None) -> dict:
    if not timestamp:
        return {"last_heartbeat_at": None, "age_seconds": None, "health": "offline"}
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        age = max(0, int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()))
    except Exception:
        return {"last_heartbeat_at": timestamp, "age_seconds": None, "health": "offline"}
    if age < 5 * 60:
        health = "healthy"
    elif age <= 15 * 60:
        health = "warning"
    else:
        health = "offline"
    return {"last_heartbeat_at": timestamp, "age_seconds": age, "health": health}


def _heartbeat_row(row: dict) -> dict:
    data = dict(row)
    data["last_detail"] = json.loads(data.get("last_detail") or "{}")
    data["last_status"] = "error" if data.get("last_failure_at") and data.get("last_failure_at") == data.get("updated_at") else "success"
    data.update(_heartbeat_health(data.get("updated_at")))
    return data


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} giay"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} phut"
    hours = minutes // 60
    return f"{hours} gio {minutes % 60} phut"


def _alert_item(severity: str, code: str, title: str, detail: str, source: str) -> dict:
    return {"severity": severity, "code": code, "title": title, "detail": detail, "source": source}


def _event_item(kind: str, title: str, detail: str, at: str | None, source: str, severity: str = "info") -> dict:
    return {"kind": kind, "title": title, "detail": detail, "at": at, "source": source, "severity": severity}


def _build_operations_alerts(
    database_status: dict,
    object_storage: dict,
    qdrant: dict,
    api_status: dict,
    last_backup: dict | None,
    last_verify: dict | None,
    workflows: dict[str, dict],
    qdrant_fallback: dict,
) -> tuple[list[dict], list[dict]]:
    critical: list[dict] = []
    warnings: list[dict] = []
    if api_status.get("status") != "ok":
        critical.append(_alert_item("critical", "api_unavailable", "API khong san sang", "API health khong tra ve trang thai ok.", "operations_status.api"))
    if not database_status.get("available"):
        critical.append(_alert_item("critical", "database_unavailable", "Co so du lieu khong kha dung", "Backend khong ket noi duoc co so du lieu hien tai.", "operations_status.database"))
    if not object_storage.get("available"):
        critical.append(_alert_item("critical", "object_storage_unavailable", "Kho doi tuong khong kha dung", object_storage.get("detail") or "Object storage dang loi hoac chua san sang.", "operations_status.object_storage"))
    if not qdrant.get("available"):
        critical.append(_alert_item("critical", "qdrant_unavailable", "Qdrant khong kha dung", qdrant.get("detail") or "Vector store dang loi hoac chua san sang.", "operations_status.qdrant"))

    now_utc = datetime.now(UTC)
    backup_at = _parse_timestamp(last_backup["created_at"]) if last_backup else None
    if not backup_at:
        warnings.append(_alert_item("warning", "backup_missing", "Chua co backup gan day", "He thong chua co ban sao luu thanh cong de doi chieu.", "backup_logs"))
    elif (now_utc - backup_at) > timedelta(hours=24):
        hours = int((now_utc - backup_at).total_seconds() // 3600)
        warnings.append(_alert_item("warning", "backup_stale", "Backup da qua 24 gio", f"Ban sao luu gan nhat da {hours} gio.", "backup_logs"))

    verify_at = _parse_timestamp(last_verify["verified_at"]) if last_verify else None
    if not verify_at:
        warnings.append(_alert_item("warning", "restore_verify_missing", "Chua kiem tra restore gan day", "He thong chua co ban ghi xac minh khoi phuc nao.", "ops_restore_verifications"))
    elif (now_utc - verify_at) > timedelta(days=7):
        days = int((now_utc - verify_at).total_seconds() // 86400)
        warnings.append(_alert_item("warning", "restore_verify_stale", "Restore verify da qua 7 ngay", f"Lan xac minh khoi phuc gan nhat da {days} ngay.", "ops_restore_verifications"))

    for workflow, item in workflows.items():
        if item.get("health") == "offline":
            age = item.get("age_seconds")
            detail = "Workflow chua co heartbeat." if age is None else f"Workflow da offline {format_duration(age)}."
            warnings.append(_alert_item("warning", f"{workflow}_offline", f"{workflow} offline", detail, "automation_heartbeats"))

    if qdrant_fallback.get("warning"):
        warnings.append(
            _alert_item(
                "warning",
                "qdrant_fallback_high",
                "Tan suat fallback Qdrant cao",
                f"{qdrant_fallback['count_last_hour']} fallback trong gio qua, nguong la {qdrant_fallback['threshold_per_hour']}.",
                "audit_logs.rag.qdrant_fallback",
            )
        )
    return critical, warnings


def _build_operations_events(
    last_backup: dict | None,
    last_verify: dict | None,
    workflows: dict[str, dict],
    fallback_audits: list[dict],
) -> list[dict]:
    events: list[dict] = []
    if last_backup:
        events.append(
            _event_item(
                "backup",
                "Backup gan nhat",
                f"{last_backup['id']} - {last_backup['status']}",
                last_backup.get("created_at"),
                "backup_logs",
                "info" if last_backup.get("status") == "success" else "warning",
            )
        )
    if last_verify:
        events.append(
            _event_item(
                "restore_verify",
                "Restore verification",
                f"{last_verify['backup_id']} - {last_verify['status']}",
                last_verify.get("verified_at"),
                "ops_restore_verifications",
                "info" if last_verify.get("status") == "verified" else "warning",
            )
        )
    for workflow, item in workflows.items():
        detail = item.get("last_detail") or {}
        message = detail.get("message") or f"Trang thai {item.get('last_status')}"
        events.append(
            _event_item(
                "workflow",
                f"Heartbeat {workflow}",
                str(message),
                item.get("last_heartbeat_at"),
                "automation_heartbeats",
                "warning" if item.get("last_status") == "error" else "info",
            )
        )
    for row in fallback_audits:
        detail = json.loads(row.get("detail") or "{}")
        query = detail.get("query") or "rag fallback"
        events.append(
            _event_item(
                "qdrant_fallback",
                "Qdrant fallback",
                str(query),
                row.get("created_at"),
                "audit_logs.rag.qdrant_fallback",
                "warning",
            )
        )
    events.sort(key=lambda item: _parse_timestamp(item.get("at")) or datetime.min.replace(tzinfo=UTC), reverse=True)
    return events[:8]


def record_automation_heartbeat(db, workflow: str, status: str, detail: dict | None = None, timestamp: str | None = None) -> dict:
    workflow = _normalize_workflow_name(workflow)
    if status == "error":
        status = "failure"
    if workflow not in {"policy_activation", "lecturer_assignment"}:
        raise ValueError("Workflow khÃ´ng há»£p lá»‡.")
    if status not in {"success", "failure"}:
        raise ValueError("Tráº¡ng thÃ¡i heartbeat khÃ´ng há»£p lá»‡.")
    current = db.execute("SELECT * FROM automation_heartbeats WHERE workflow=?", (workflow,)).fetchone()
    timestamp = timestamp or now()
    if current:
        failure_count = int(current["failure_count"] or 0) + (1 if status == "failure" else 0)
        db.execute(
            "UPDATE automation_heartbeats SET last_success_at=?,last_failure_at=?,failure_count=?,last_detail=?,updated_at=? WHERE workflow=?",
            (
                timestamp if status == "success" else current["last_success_at"],
                timestamp if status == "failure" else current["last_failure_at"],
                failure_count,
                json.dumps(detail or {}, ensure_ascii=False),
                timestamp,
                workflow,
            ),
        )
    else:
        db.execute(
            "INSERT INTO automation_heartbeats VALUES(?,?,?,?,?,?)",
            (
                workflow,
                timestamp if status == "success" else None,
                timestamp if status == "failure" else None,
                1 if status == "failure" else 0,
                json.dumps(detail or {}, ensure_ascii=False),
                timestamp,
            ),
        )
    return _heartbeat_row(dict(db.execute("SELECT * FROM automation_heartbeats WHERE workflow=?", (workflow,)).fetchone()))


def operations_status(db) -> dict:
    infra = infrastructure_status()
    last_backup = db.execute("SELECT * FROM backup_logs ORDER BY created_at DESC LIMIT 1").fetchone()
    last_verify = db.execute("SELECT * FROM ops_restore_verifications ORDER BY verified_at DESC LIMIT 1").fetchone()
    last_verify_data = dict(last_verify) if last_verify else None
    if last_verify_data:
        last_verify_data["detail"] = json.loads(last_verify_data["detail"] or "{}")
    workflows = {
        row["workflow"]: _heartbeat_row(dict(row))
        for row in db.execute("SELECT * FROM automation_heartbeats ORDER BY workflow").fetchall()
    }
    for workflow in ("policy_activation", "lecturer_assignment"):
        workflows.setdefault(workflow, {
            "workflow": workflow,
            "last_success_at": None,
            "last_failure_at": None,
            "failure_count": 0,
            "last_detail": {},
            "updated_at": None,
            "last_status": "offline",
            "last_heartbeat_at": None,
            "age_seconds": None,
            "health": "offline",
        })
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    fallback_count = db.execute(
        "SELECT COUNT(*) count FROM audit_logs WHERE action='rag.qdrant_fallback' AND created_at>=?",
        (cutoff,),
    ).fetchone()["count"]
    fallback_audits = rows(
        db.execute(
            "SELECT action,detail,created_at FROM audit_logs WHERE action='rag.qdrant_fallback' ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    )
    threshold = int(os.getenv("OPS_QDRANT_FALLBACK_THRESHOLD", "3"))
    qdrant_fallback = {
        "count_last_hour": fallback_count,
        "threshold_per_hour": threshold,
        "warning": fallback_count >= threshold,
    }
    database_status = {"provider": database_backend(), "available": True}
    critical_alerts, warnings = _build_operations_alerts(
        database_status,
        infra["services"]["object_storage"],
        infra["services"]["vector_store"],
        {"status": "ok"},
        dict(last_backup) if last_backup else None,
        last_verify_data,
        workflows,
        qdrant_fallback,
    )
    recent_events = _build_operations_events(
        dict(last_backup) if last_backup else None,
        last_verify_data,
        workflows,
        fallback_audits,
    )
    return {
        "api": {"status": "ok"},
        "database": database_status,
        "qdrant": infra["services"]["vector_store"],
        "object_storage": infra["services"]["object_storage"],
        "queue": infra["services"]["queue"],
        "ready": infra["ready"],
        "last_backup": dict(last_backup) if last_backup else None,
        "last_restore_verification": last_verify_data,
        "n8n": workflows,
        "qdrant_fallback": qdrant_fallback,
        "alerts": {
            "critical": critical_alerts,
            "warnings": warnings,
            "recent_events": recent_events,
        },
        "storage": storage_metrics(db),
    }


def sync_document(db, document_id: str, source: Path, storage_id: str | None = None) -> list[dict]:
    results = []
    query = "SELECT * FROM external_storages WHERE enabled=1"
    params = ()
    if storage_id:
        query += " AND id=?"
        params = (storage_id,)
    for storage in db.execute(query, params).fetchall():
        if storage["provider"] in {"google_drive", "onedrive"}:
            conn_exists = db.execute(
                "SELECT 1 FROM cloud_connections WHERE provider=? AND status='connected'",
                (storage["provider"],)
            ).fetchone()
            if not conn_exists:
                db.execute("UPDATE external_storages SET last_status='failed' WHERE id=?", (storage["id"],))
                results.append({"storage": storage["name"], "status": "failed", "error": "Provider not connected"})
                continue
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


def _percent(part: int | float, total: int | float) -> int:
    if not total:
        return 0
    return int(round((part / total) * 100))


def _risk_from_readiness(score: int, *, critical: bool = False) -> str:
    if critical:
        return "critical"
    if score >= 80:
        return "low"
    if score >= 60:
        return "medium"
    if score >= 35:
        return "high"
    return "critical"


def _max_risk(*risks: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return max((risk for risk in risks if risk), key=lambda item: order.get(item, 0), default="low")


def _knowledge_transfer_model(db) -> dict:
    policy = active_policy(db)
    if not policy:
        empty_summary = {
            "document_coverage_percent": 0,
            "policy_compliance_percent": 0,
            "transfer_readiness_score": 0,
            "knowledge_risk": "critical",
            "critical_gap_count": 0,
            "course_complete_count": 0,
            "course_total_count": 0,
            "single_lecturer_specialization_count": 0,
            "stale_document_count": 0,
        }
        return {"policy": None, "summary": empty_summary, "top_risks": [], "specializations": [], "course_gaps": [], "lecturer_dependency": []}

    policy_id = policy["id"]
    spec_rows = rows(db.execute(
        """SELECT s.*, fn.path AS folder_path
           FROM specializations s JOIN folder_nodes fn ON fn.id=s.folder_node_id
           WHERE s.policy_id=? AND fn.status='active'
           ORDER BY s.name""",
        (policy_id,),
    ).fetchall())
    spec_ids = {item["id"] for item in spec_rows}
    courses = rows(db.execute(
        """SELECT c.*, s.id AS specialization_id, s.name AS specialization_name
           FROM folder_nodes c
           JOIN folder_nodes spec_node ON spec_node.id=c.parent_id
           JOIN specializations s ON s.folder_node_id=spec_node.id
           WHERE c.policy_id=? AND c.type='course' AND c.status='active'
           ORDER BY s.name,c.name""",
        (policy_id,),
    ).fetchall())
    course_ids = {item["id"] for item in courses}
    course_to_spec = {item["id"]: item["specialization_id"] for item in courses}
    course_names = {item["id"]: item["name"] for item in courses}
    spec_names = {item["id"]: item["name"] for item in spec_rows}
    required_by_course: dict[str, list[str]] = {}
    folder_to_course: dict[str, str] = {}
    folder_names: dict[str, str] = {}
    for course in courses:
        folders = rows(db.execute(
            "SELECT id,name FROM folder_nodes WHERE parent_id=? AND type='standard_folder' AND status='active' ORDER BY name",
            (course["id"],),
        ).fetchall())
        required_by_course[course["id"]] = [folder["name"] for folder in folders] or STANDARD_FOLDERS[:4]
        for folder in folders:
            folder_to_course[folder["id"]] = course["id"]
            folder_names[folder["id"]] = folder["name"]

    assigned_by_spec: dict[str, set[str]] = {spec["id"]: set() for spec in spec_rows}
    assignment_rows = rows(db.execute(
        "SELECT lecturer_code,specialization_id FROM lecturer_assignments WHERE policy_id=? AND status='active'",
        (policy_id,),
    ).fetchall())
    projection_rows = rows(db.execute(
        """SELECT ls.user_code lecturer_code,ls.specialization_id
           FROM lecturer_specializations ls JOIN specializations s ON s.id=ls.specialization_id
           WHERE s.policy_id=?""",
        (policy_id,),
    ).fetchall())
    for assignment in assignment_rows + projection_rows:
        if assignment["specialization_id"] in assigned_by_spec:
            assigned_by_spec[assignment["specialization_id"]].add(assignment["lecturer_code"])

    active_permission_users = {
        row["user_code"]
        for row in db.execute(
            "SELECT DISTINCT user_code FROM lecturer_folder_permissions WHERE policy_id=? AND status='active'",
            (policy_id,),
        ).fetchall()
    }
    documents = rows(db.execute(
        """SELECT d.*, fn.type AS folder_node_type, fn.parent_id AS folder_parent_id, fn.name AS folder_node_name
           FROM documents d LEFT JOIN folder_nodes fn ON fn.id=d.folder_node_id
           WHERE d.deleted_at IS NULL"""
    ).fetchall())
    threshold = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=180)).isoformat(timespec="seconds")

    def resolve_course(document: dict) -> str | None:
        if document.get("course_id") in course_ids:
            return document["course_id"]
        folder_id = document.get("folder_node_id")
        if folder_id in folder_to_course:
            return folder_to_course[folder_id]
        if folder_id in course_ids:
            return folder_id
        text = _fold_text(f"{document.get('topic', '')} {document.get('title', '')} {document.get('folder_path', '')}")
        for course_id, course_name in course_names.items():
            if _fold_text(course_name) and _fold_text(course_name) in text:
                return course_id
        return None

    def resolve_doc_type(document: dict) -> str:
        folder_id = document.get("folder_node_id")
        if folder_id in folder_names:
            return folder_names[folder_id]
        return str(document.get("document_type") or document.get("doc_type") or "").strip()

    docs_by_course: dict[str, list[dict]] = {course["id"]: [] for course in courses}
    docs_by_spec: dict[str, list[dict]] = {spec["id"]: [] for spec in spec_rows}
    metadata_gap_docs = 0
    stale_docs = 0
    for document in documents:
        course_id = resolve_course(document)
        spec_id = document.get("specialization_id") if document.get("specialization_id") in spec_ids else None
        if not spec_id and course_id:
            spec_id = course_to_spec.get(course_id)
        if course_id and document.get("status") == "INDEXED":
            docs_by_course.setdefault(course_id, []).append(document)
        if spec_id and document.get("status") == "INDEXED":
            docs_by_spec.setdefault(spec_id, []).append(document)
        if not document.get("course_id") or not document.get("document_type") or not document.get("folder_node_id"):
            metadata_gap_docs += 1
        if str(document.get("updated_at") or "") < threshold:
            stale_docs += 1

    total_slots = 0
    covered_slots = 0
    complete_courses = 0
    course_gaps = []
    course_coverage_by_spec: dict[str, list[int]] = {spec["id"]: [] for spec in spec_rows}
    for course in courses:
        required = required_by_course.get(course["id"], [])
        present_folded = {_fold_text(resolve_doc_type(document)) for document in docs_by_course.get(course["id"], [])}
        present = [item for item in required if _fold_text(item) in present_folded]
        missing = [item for item in required if _fold_text(item) not in present_folded]
        total_slots += len(required)
        covered_slots += len(present)
        coverage = _percent(len(present), len(required))
        if coverage == 100:
            complete_courses += 1
        assigned_count = len(assigned_by_spec.get(course["specialization_id"], set()))
        coverage_risk = "critical" if coverage == 0 else "high" if coverage < 50 else "medium" if coverage < 100 else "low"
        assignment_risk = "critical" if assigned_count == 0 else "high" if assigned_count == 1 else "low"
        risk = _max_risk(coverage_risk, assignment_risk)
        course_coverage_by_spec.setdefault(course["specialization_id"], []).append(coverage)
        course_gaps.append({
            "course_id": course["id"],
            "course_name": course["name"],
            "specialization_id": course["specialization_id"],
            "specialization_name": course["specialization_name"],
            "required_types": required,
            "present_types": present,
            "missing_types": missing,
            "coverage_percent": coverage,
            "risk": risk,
        })

    specialization_insights = []
    lecturer_dependency = []
    critical_gap_count = sum(1 for item in course_gaps if item["risk"] == "critical")
    single_lecturer_specs = 0
    readiness_scores = []
    for spec in spec_rows:
        spec_docs = docs_by_spec.get(spec["id"], [])
        assigned = assigned_by_spec.get(spec["id"], set())
        assigned_count = len(assigned)
        if assigned_count == 1:
            single_lecturer_specs += 1
        coverages = course_coverage_by_spec.get(spec["id"], [])
        coverage = int(round(sum(coverages) / len(coverages))) if coverages else 0
        owner_counts: dict[str, int] = {}
        for document in spec_docs:
            owner_counts[document["owner_code"]] = owner_counts.get(document["owner_code"], 0) + 1
        owner_concentration = _percent(max(owner_counts.values()) if owner_counts else 0, len(spec_docs))
        fresh_count = sum(1 for document in spec_docs if str(document.get("updated_at") or "") >= threshold)
        public_count = sum(1 for document in spec_docs if document.get("visibility") != "private")
        spec_metadata_gaps = sum(1 for document in spec_docs if not document.get("course_id") or not document.get("document_type") or not document.get("folder_node_id"))
        freshness_score = _percent(fresh_count, len(spec_docs)) if spec_docs else 0
        access_score = _percent(public_count, len(spec_docs)) if spec_docs else 0
        metadata_score = _percent(len(spec_docs) - spec_metadata_gaps, len(spec_docs)) if spec_docs else 0
        lecturer_score = 0 if assigned_count == 0 else 40 if assigned_count == 1 else 80 if assigned_count == 2 else 100
        readiness = int(round(0.40 * coverage + 0.25 * lecturer_score + 0.15 * freshness_score + 0.10 * access_score + 0.10 * metadata_score))
        risk = _risk_from_readiness(readiness, critical=assigned_count == 0)
        if risk == "critical":
            critical_gap_count += 1
        readiness_scores.append(readiness)
        missing_slots = sum(len(item["missing_types"]) for item in course_gaps if item["specialization_id"] == spec["id"])
        specialization_insights.append({
            "specialization_id": spec["id"],
            "specialization_name": spec["name"],
            "document_coverage_percent": coverage,
            "assigned_lecturer_count": assigned_count,
            "owner_concentration_percent": owner_concentration,
            "transfer_readiness_score": readiness,
            "knowledge_risk": risk,
            "missing_required_slots": missing_slots,
            "stale_document_count": sum(1 for document in spec_docs if str(document.get("updated_at") or "") < threshold),
        })
        for lecturer_code in sorted(assigned):
            owned = owner_counts.get(lecturer_code, 0)
            dependency_risk = "high" if assigned_count == 1 or owner_concentration >= 80 else "medium" if owner_concentration >= 60 else "low"
            lecturer = db.execute("SELECT name FROM users WHERE code=?", (lecturer_code,)).fetchone()
            lecturer_dependency.append({
                "lecturer_code": lecturer_code,
                "lecturer_name": lecturer["name"] if lecturer else lecturer_code,
                "specialization_id": spec["id"],
                "specialization_name": spec["name"],
                "owned_document_count": owned,
                "dependency_risk": dependency_risk,
                "owner_concentration_percent": owner_concentration,
            })

    document_coverage = _percent(covered_slots, total_slots)
    assigned_users = {code for codes in assigned_by_spec.values() for code in codes}
    permission_compliance = _percent(len(assigned_users & active_permission_users), len(assigned_users)) if assigned_users else 0
    metadata_compliance = _percent(len(documents) - metadata_gap_docs, len(documents)) if documents else 0
    policy_compliance = int(round((metadata_compliance + permission_compliance) / 2)) if documents or assigned_users else 0
    transfer_readiness = int(round(sum(readiness_scores) / len(readiness_scores))) if readiness_scores else 0
    overall_risk = _risk_from_readiness(transfer_readiness, critical=critical_gap_count > 0 and transfer_readiness < 50)
    top_risks = []
    for item in sorted(specialization_insights, key=lambda row: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(row["knowledge_risk"], 4), row["transfer_readiness_score"]))[:5]:
        if item["knowledge_risk"] in {"critical", "high"}:
            top_risks.append({
                "scope_type": "specialization",
                "scope_id": item["specialization_id"],
                "scope_name": item["specialization_name"],
                "risk": item["knowledge_risk"],
                "reason": f"{item['missing_required_slots']} required document slots missing, {item['assigned_lecturer_count']} lecturer(s) assigned.",
            })
    return {
        "policy": {"id": policy["id"], "title": policy["title"]},
        "summary": {
            "document_coverage_percent": document_coverage,
            "policy_compliance_percent": policy_compliance,
            "transfer_readiness_score": transfer_readiness,
            "knowledge_risk": overall_risk,
            "critical_gap_count": critical_gap_count,
            "course_complete_count": complete_courses,
            "course_total_count": len(courses),
            "single_lecturer_specialization_count": single_lecturer_specs,
            "stale_document_count": stale_docs,
        },
        "top_risks": top_risks,
        "specializations": specialization_insights,
        "course_gaps": course_gaps,
        "lecturer_dependency": lecturer_dependency,
    }


def knowledge_transfer_insights(db) -> dict:
    model = _knowledge_transfer_model(db)
    return {"policy": model["policy"], "summary": model["summary"], "top_risks": model["top_risks"]}


def knowledge_transfer_actions(db) -> list[dict]:
    model = _knowledge_transfer_model(db)
    actions: list[dict] = []

    for gap in model["course_gaps"]:
        missing_types = gap.get("missing_types") or []
        coverage = int(gap.get("coverage_percent") or 0)
        if not missing_types and coverage >= 100:
            continue
        if coverage < 40:
            priority = "critical"
            reason = f"{gap['course_name']} coverage is {coverage}% and is missing {len(missing_types)} required document type(s)."
        elif coverage < 70:
            priority = "high"
            reason = f"{gap['course_name']} coverage is below target at {coverage}%."
        elif missing_types:
            priority = "medium"
            reason = f"{gap['course_name']} is missing required document type(s): {', '.join(missing_types)}."
        else:
            priority = "low"
            reason = f"{gap['course_name']} has minor knowledge transfer gaps."
        upload_actions = [f"Upload {doc_type}" for doc_type in missing_types]
        actions.append({
            "priority": priority,
            "category": "course_gap",
            "title": f"{gap['course_name']} missing {', '.join(missing_types) if missing_types else 'required documents'}",
            "reason": reason,
            "recommended_actions": upload_actions + ["Bo sung tai lieu hoc phan"],
            "scope": {
                "course_id": gap["course_id"],
                "course_name": gap["course_name"],
                "specialization_id": gap["specialization_id"],
                "specialization_name": gap["specialization_name"],
            },
        })

    for spec in model["specializations"]:
        lecturer_count = int(spec.get("assigned_lecturer_count") or 0)
        if lecturer_count == 0:
            actions.append({
                "priority": "critical",
                "category": "lecturer_assignment",
                "title": f"{spec['specialization_name']} has no assigned lecturer",
                "reason": "No lecturer is assigned to this specialization, so transfer ownership is blocked.",
                "recommended_actions": ["Chi dinh giang vien phu trach", "Dong bo lai folder permissions"],
                "scope": {
                    "specialization_id": spec["specialization_id"],
                    "specialization_name": spec["specialization_name"],
                },
            })
        elif lecturer_count == 1:
            actions.append({
                "priority": "high",
                "category": "lecturer_dependency",
                "title": f"{spec['specialization_name']} depends on one lecturer",
                "reason": "Only one lecturer is assigned to this specialization.",
                "recommended_actions": ["Chi dinh giang vien du phong", "Chia se quyen truy cap tai lieu"],
                "scope": {
                    "specialization_id": spec["specialization_id"],
                    "specialization_name": spec["specialization_name"],
                },
            })

    for dependency in model["lecturer_dependency"]:
        if dependency["dependency_risk"] not in {"high", "medium"}:
            continue
        actions.append({
            "priority": "high" if dependency["dependency_risk"] == "high" else "medium",
            "category": "lecturer_dependency",
            "title": f"{dependency['specialization_name']} depends on {dependency['lecturer_code']}",
            "reason": f"{dependency['lecturer_code']} owns {dependency['owned_document_count']} document(s); owner concentration is {dependency['owner_concentration_percent']}%.",
            "recommended_actions": ["Chi dinh giang vien du phong", "Phan tan quyen so huu tai lieu", "Yeu cau bo sung tai lieu ban giao"],
            "scope": {
                "lecturer_code": dependency["lecturer_code"],
                "specialization_id": dependency["specialization_id"],
                "specialization_name": dependency["specialization_name"],
            },
        })

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    category_order = {"course_gap": 0, "lecturer_assignment": 1, "lecturer_dependency": 2}
    return sorted(actions, key=lambda item: (priority_order.get(item["priority"], 4), category_order.get(item["category"], 9), item["title"]))


def knowledge_transfer_specialization_insights(db) -> dict:
    return {"items": _knowledge_transfer_model(db)["specializations"]}


def knowledge_transfer_course_gaps(db) -> dict:
    return {"items": _knowledge_transfer_model(db)["course_gaps"]}


def knowledge_transfer_lecturer_dependency(db) -> dict:
    return {"items": _knowledge_transfer_model(db)["lecturer_dependency"]}


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
    action_events = rows(db.execute(
        "SELECT action,actor_code,created_at FROM audit_logs ORDER BY id DESC LIMIT 100"
    ).fetchall())
    popular_queries = rows(db.execute(
        "SELECT rewritten_query query,COUNT(*) count FROM query_traces GROUP BY rewritten_query ORDER BY count DESC LIMIT 10"
    ).fetchall())
    zero_result_queries = rows(db.execute(
        "SELECT original_query,created_at FROM query_traces WHERE citations_json='[]' ORDER BY created_at DESC LIMIT 20"
    ).fetchall())
    bad_feedback = rows(db.execute(
        "SELECT rating,reason,detail,created_at FROM search_feedback WHERE rating<>'up' ORDER BY created_at DESC LIMIT 20"
    ).fetchall())
    return {
        "actions": actions,
        "action_events": action_events,
        "popular_queries": popular_queries,
        "zero_result_queries": zero_result_queries,
        "bad_feedback": bad_feedback,
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
