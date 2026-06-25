from __future__ import annotations

import json
import os
import re
import urllib.request
import uuid

from .database import now, rows


NODE_TYPES = {"faculty", "department", "specialization", "course", "standard_folder", "folder"}
RULE_TYPES = {"permission", "storage_rule", "retention", "visibility"}
ACTION_TYPES = {"add_node", "move_node", "rename_node", "delete_node", "update_permission", "update_storage_rule"}


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _load(value: str | None, fallback=None):
    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {} if fallback is None else fallback


def _strip_accents(value: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _fold(value: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(value).casefold()).strip()


def _active_policy_id(db) -> str | None:
    row = db.execute("SELECT id FROM policy_files WHERE status='active' ORDER BY activated_at DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def policy_audit(db, actor: dict, action: str, target_type: str, target_id: str | None, before, after, status: str = "success", message: str = "") -> dict:
    audit_id = _id("paudit")
    db.execute(
        """INSERT INTO policy_audit_logs(id,actor_code,action,target_type,target_id,before_json,after_json,status,message,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (audit_id, actor["code"], action, target_type, target_id, _json(before), _json(after), status, message, now()),
    )
    return dict(db.execute("SELECT * FROM policy_audit_logs WHERE id=?", (audit_id,)).fetchone())


def sync_policy_nodes_from_folder_nodes(db, actor: dict | None = None) -> None:
    policy_id = _active_policy_id(db)
    if not policy_id:
        return
    timestamp = now()
    existing = {
        row["source_folder_node_id"]
        for row in db.execute("SELECT source_folder_node_id FROM policy_nodes WHERE active_policy_id=?", (policy_id,)).fetchall()
        if row["source_folder_node_id"]
    }
    for node in db.execute("SELECT * FROM folder_nodes WHERE policy_id=? AND status='active'", (policy_id,)).fetchall():
        if node["id"] in existing:
            db.execute(
                """UPDATE policy_nodes SET name=?,parent_id=?,node_type=?,path=?,status=?,updated_at=?
                   WHERE active_policy_id=? AND source_folder_node_id=?""",
                (node["name"], node["parent_id"], node["type"], node["path"], node["status"], timestamp, policy_id, node["id"]),
            )
            continue
        db.execute(
            """INSERT INTO policy_nodes(id,active_policy_id,name,parent_id,node_type,path,status,metadata_json,source_folder_node_id,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _id("pnode"), policy_id, node["name"], node["parent_id"], node["type"], node["path"], node["status"],
                _json({"synced_from": "folder_nodes"}), node["id"], actor["code"] if actor else "ADMIN", timestamp, timestamp,
            ),
        )


def policy_node_public(row) -> dict:
    item = dict(row)
    item["metadata"] = _load(item.pop("metadata_json", "{}"))
    return item


def policy_rule_public(row) -> dict:
    item = dict(row)
    item["value"] = _load(item.pop("value_json", "{}"))
    return item


def list_policy_nodes(db, actor: dict | None = None) -> list[dict]:
    sync_policy_nodes_from_folder_nodes(db, actor)
    policy_id = _active_policy_id(db)
    if not policy_id:
        return []
    return [policy_node_public(row) for row in db.execute("SELECT * FROM policy_nodes WHERE active_policy_id=? ORDER BY path", (policy_id,)).fetchall()]


def get_policy_node(db, node_id: str):
    row = db.execute("SELECT * FROM policy_nodes WHERE id=? OR source_folder_node_id=?", (node_id, node_id)).fetchone()
    return dict(row) if row else None


def _folder_node_for_policy_node(db, node: dict | None):
    if not node:
        return None
    source_id = node.get("source_folder_node_id")
    if not source_id:
        return None
    row = db.execute("SELECT * FROM folder_nodes WHERE id=?", (source_id,)).fetchone()
    return dict(row) if row else None


def _path_for(db, parent_id: str | None, name: str) -> str:
    if not parent_id:
        return name
    parent = db.execute("SELECT path FROM folder_nodes WHERE id=?", (parent_id,)).fetchone()
    if not parent:
        raise ValueError("Parent node khong ton tai trong Knowledge Tree.")
    return f"{parent['path']}/{name}"


def _repath_children(db, folder_node_id: str, base_path: str, timestamp: str) -> None:
    for child in db.execute("SELECT * FROM folder_nodes WHERE parent_id=? AND status='active'", (folder_node_id,)).fetchall():
        child_path = f"{base_path}/{child['name']}"
        db.execute("UPDATE folder_nodes SET path=?,updated_at=? WHERE id=?", (child_path, timestamp, child["id"]))
        db.execute("UPDATE policy_nodes SET path=?,updated_at=? WHERE source_folder_node_id=?", (child_path, timestamp, child["id"]))
        _repath_children(db, child["id"], child_path, timestamp)


def create_policy_node(db, actor: dict, payload: dict) -> dict:
    policy_id = _active_policy_id(db)
    if not policy_id:
        raise ValueError("Chua co policy active de them node.")
    name = str(payload.get("name") or "").strip()
    node_type = str(payload.get("node_type") or payload.get("type") or "folder").strip()
    parent_id = payload.get("parent_id")
    if not name:
        raise ValueError("Ten node khong duoc de trong.")
    if node_type not in NODE_TYPES:
        raise ValueError(f"node_type khong hop le. Cho phep: {', '.join(sorted(NODE_TYPES))}.")
    if parent_id:
        parent = db.execute("SELECT * FROM folder_nodes WHERE id=? AND status='active'", (parent_id,)).fetchone()
        if not parent:
            parent_policy_node = get_policy_node(db, parent_id)
            parent = db.execute("SELECT * FROM folder_nodes WHERE id=?", (parent_policy_node["source_folder_node_id"],)).fetchone() if parent_policy_node else None
        if not parent:
            raise ValueError("Parent node khong ton tai.")
        parent_id = parent["id"]
    timestamp = now()
    folder_id = _id("node")
    path = _path_for(db, parent_id, name)
    db.execute(
        "INSERT INTO folder_nodes(id,policy_id,name,parent_id,type,path,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (folder_id, policy_id, name, parent_id, node_type, path, "active", timestamp, timestamp),
    )
    if node_type == "specialization":
        db.execute(
            "INSERT INTO specializations(id,name,description,policy_id,folder_node_id) VALUES(?,?,?,?,?)",
            (_id("spec"), name, str(payload.get("description") or ""), policy_id, folder_id),
        )
    policy_node_id = _id("pnode")
    db.execute(
        """INSERT INTO policy_nodes(id,active_policy_id,name,parent_id,node_type,path,status,metadata_json,source_folder_node_id,created_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (policy_node_id, policy_id, name, parent_id, node_type, path, "active", _json(payload.get("metadata")), folder_id, actor["code"], timestamp, timestamp),
    )
    created = policy_node_public(db.execute("SELECT * FROM policy_nodes WHERE id=?", (policy_node_id,)).fetchone())
    policy_audit(db, actor, "policy.node.create", "policy_node", policy_node_id, None, created)
    return created


def update_policy_node(db, actor: dict, node_id: str, payload: dict) -> dict:
    node = get_policy_node(db, node_id)
    if not node:
        raise ValueError("Policy node khong ton tai.")
    folder = _folder_node_for_policy_node(db, node)
    if not folder:
        raise ValueError("Policy node chua lien ket Knowledge Tree.")
    before = {**policy_node_public(node), "folder_node": folder}
    name = str(payload.get("name") or node["name"]).strip()
    node_type = str(payload.get("node_type") or payload.get("type") or node["node_type"]).strip()
    parent_id = payload.get("parent_id", folder.get("parent_id"))
    if node_type not in NODE_TYPES:
        raise ValueError("node_type khong hop le.")
    if parent_id:
        parent_node = db.execute("SELECT * FROM folder_nodes WHERE id=? AND status='active'", (parent_id,)).fetchone()
        if not parent_node:
            policy_parent = get_policy_node(db, parent_id)
            parent_node = db.execute("SELECT * FROM folder_nodes WHERE id=?", (policy_parent["source_folder_node_id"],)).fetchone() if policy_parent else None
        if not parent_node:
            raise ValueError("Parent node khong ton tai.")
        parent_id = parent_node["id"]
        if parent_id == folder["id"]:
            raise ValueError("Khong the chuyen node vao chinh no.")
    timestamp = now()
    path = _path_for(db, parent_id, name)
    db.execute("UPDATE folder_nodes SET name=?,parent_id=?,type=?,path=?,updated_at=? WHERE id=?", (name, parent_id, node_type, path, timestamp, folder["id"]))
    db.execute(
        "UPDATE policy_nodes SET name=?,parent_id=?,node_type=?,path=?,metadata_json=?,updated_at=? WHERE id=?",
        (name, parent_id, node_type, path, _json(payload.get("metadata", _load(node.get("metadata_json")))), timestamp, node["id"]),
    )
    _repath_children(db, folder["id"], path, timestamp)
    after = policy_node_public(db.execute("SELECT * FROM policy_nodes WHERE id=?", (node["id"],)).fetchone())
    policy_audit(db, actor, "policy.node.update", "policy_node", node["id"], before, after)
    return after


def delete_policy_node(db, actor: dict, node_id: str) -> dict:
    node = get_policy_node(db, node_id)
    if not node:
        raise ValueError("Policy node khong ton tai.")
    folder = _folder_node_for_policy_node(db, node)
    before = policy_node_public(node)
    timestamp = now()
    ids = [folder["id"]] if folder else []
    index = 0
    while index < len(ids):
        item = ids[index]
        ids.extend(row["id"] for row in db.execute("SELECT id FROM folder_nodes WHERE parent_id=? AND status='active'", (item,)).fetchall())
        index += 1
    for folder_id in ids:
        db.execute("UPDATE folder_nodes SET status='deprecated',updated_at=? WHERE id=?", (timestamp, folder_id))
        db.execute("UPDATE policy_nodes SET status='deprecated',updated_at=? WHERE source_folder_node_id=?", (timestamp, folder_id))
    if not ids:
        db.execute("UPDATE policy_nodes SET status='deprecated',updated_at=? WHERE id=?", (timestamp, node["id"]))
    after = policy_node_public(db.execute("SELECT * FROM policy_nodes WHERE id=?", (node["id"],)).fetchone())
    policy_audit(db, actor, "policy.node.delete", "policy_node", node["id"], before, after)
    return after


def list_policy_rules(db) -> list[dict]:
    policy_id = _active_policy_id(db)
    if policy_id:
        query = "SELECT * FROM policy_rules WHERE active_policy_id=? ORDER BY updated_at DESC"
        params = (policy_id,)
    else:
        query = "SELECT * FROM policy_rules WHERE active_policy_id IS NULL ORDER BY updated_at DESC"
        params = ()
    return [policy_rule_public(row) for row in db.execute(query, params).fetchall()]


def create_policy_rule(db, actor: dict, payload: dict) -> dict:
    rule_type = str(payload.get("rule_type") or "").strip()
    scope_type = str(payload.get("scope_type") or "faculty").strip()
    if rule_type not in RULE_TYPES:
        raise ValueError(f"rule_type khong hop le. Cho phep: {', '.join(sorted(RULE_TYPES))}.")
    timestamp = now()
    rule_id = _id("prule")
    db.execute(
        """INSERT INTO policy_rules(id,active_policy_id,rule_type,scope_type,scope_id,value_json,status,created_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            rule_id, _active_policy_id(db), rule_type, scope_type, payload.get("scope_id"),
            _json(payload.get("value") or {}), str(payload.get("status") or "active"),
            actor["code"], timestamp, timestamp,
        ),
    )
    created = policy_rule_public(db.execute("SELECT * FROM policy_rules WHERE id=?", (rule_id,)).fetchone())
    policy_audit(db, actor, "policy.rule.create", "policy_rule", rule_id, None, created)
    return created


def update_policy_rule(db, actor: dict, rule_id: str, payload: dict) -> dict:
    row = db.execute("SELECT * FROM policy_rules WHERE id=?", (rule_id,)).fetchone()
    if not row:
        raise ValueError("Policy rule khong ton tai.")
    before = policy_rule_public(row)
    rule_type = str(payload.get("rule_type") or row["rule_type"]).strip()
    if rule_type not in RULE_TYPES:
        raise ValueError("rule_type khong hop le.")
    timestamp = now()
    db.execute(
        "UPDATE policy_rules SET rule_type=?,scope_type=?,scope_id=?,value_json=?,status=?,updated_at=? WHERE id=?",
        (
            rule_type, str(payload.get("scope_type") or row["scope_type"]), payload.get("scope_id", row["scope_id"]),
            _json(payload.get("value", _load(row["value_json"]))), str(payload.get("status") or row["status"]),
            timestamp, rule_id,
        ),
    )
    after = policy_rule_public(db.execute("SELECT * FROM policy_rules WHERE id=?", (rule_id,)).fetchone())
    policy_audit(db, actor, "policy.rule.update", "policy_rule", rule_id, before, after)
    return after


def delete_policy_rule(db, actor: dict, rule_id: str) -> dict:
    row = db.execute("SELECT * FROM policy_rules WHERE id=?", (rule_id,)).fetchone()
    if not row:
        raise ValueError("Policy rule khong ton tai.")
    before = policy_rule_public(row)
    db.execute("UPDATE policy_rules SET status='inactive',updated_at=? WHERE id=?", (now(), rule_id))
    after = policy_rule_public(db.execute("SELECT * FROM policy_rules WHERE id=?", (rule_id,)).fetchone())
    policy_audit(db, actor, "policy.rule.delete", "policy_rule", rule_id, before, after)
    return after


def _find_folder_node(db, text: str):
    folded = _fold(text)
    candidates = rows(db.execute("SELECT * FROM folder_nodes WHERE status='active' ORDER BY LENGTH(path) DESC").fetchall())
    for node in candidates:
        if _fold(node["name"]) == folded or _fold(node["path"]) == folded:
            return node
    for node in candidates:
        if _fold(node["name"]) in folded or _fold(node["path"]) in folded:
            return node
    return None


def parse_policy_command(db, command: str) -> dict:
    text = re.sub(r"\s+", " ", (command or "").strip())
    folded = _fold(text)
    if len(text) < 6:
        return {"status": "ask_clarification", "message": "Hay nhap yeu cau policy cu the hon."}

    if any(token in folded for token in ("xoa ", "xoa nut", "xoa thu muc")):
        target = re.sub(r"^(xoa|xoa nut|xoa thu muc)\s+", "", folded).strip()
        node = _find_folder_node(db, target)
        if not node:
            return {"status": "ask_clarification", "message": "Can noi ro node can xoa.", "action": "delete_node"}
        return {"status": "need_confirmation", "action": "delete_node", "node_id": node["id"], "node_name": node["name"]}

    if any(token in folded for token in ("doi ten", "rename")):
        match = re.search(r"(?:doi ten|rename)\s+(.+?)\s+(?:thanh|to)\s+(.+)$", folded)
        if not match:
            return {"status": "ask_clarification", "message": "Hay dung dang: Doi ten <node> thanh <ten moi>.", "action": "rename_node"}
        node = _find_folder_node(db, match.group(1))
        if not node:
            return {"status": "ask_clarification", "message": "Khong tim thay node can doi ten.", "action": "rename_node"}
        return {"status": "need_confirmation", "action": "rename_node", "node_id": node["id"], "new_name": match.group(2).strip()}

    if any(token in folded for token in ("chuyen ", "di chuyen ", "move ")):
        match = re.search(r"(?:chuyen|di chuyen|move)\s+(.+?)\s+(?:vao|sang|toi|to)\s+(.+)$", folded)
        if not match:
            return {"status": "ask_clarification", "message": "Hay dung dang: Chuyen <node> vao <node cha>.", "action": "move_node"}
        node = _find_folder_node(db, match.group(1))
        parent = _find_folder_node(db, match.group(2))
        if not node or not parent:
            return {"status": "ask_clarification", "message": "Can xac dinh ro node nguon va node cha moi.", "action": "move_node"}
        return {"status": "need_confirmation", "action": "move_node", "node_id": node["id"], "new_parent_id": parent["id"]}

    if any(token in folded for token in ("quyen", "permission", "duoc xem", "chi ")) and any(token in folded for token in ("de thi", "private", "public", "xem")):
        roles = []
        if "admin" in folded or "quan tri" in folded:
            roles.append("admin")
        if "truong bo mon" in folded or "head" in folded:
            roles.append("head")
        if "giang vien" in folded:
            roles.append("lecturer")
        if not roles:
            return {"status": "ask_clarification", "message": "Can noi ro vai tro duoc phep.", "action": "update_permission"}
        return {
            "status": "need_confirmation",
            "action": "update_permission",
            "scope_type": "document_type",
            "scope_id": "Đề thi" if "de thi" in folded else None,
            "value": {"read_roles": roles},
        }

    if any(token in folded for token in ("luu vao", "noi luu", "storage", "thu muc mac dinh")):
        return {
            "status": "need_confirmation",
            "action": "update_storage_rule",
            "scope_type": "faculty",
            "value": {"instruction": text},
        }

    if any(token in folded for token in ("them ", "tao ", "bo sung ", "add ")):
        match = re.search(r"(?:them|tao|bo sung|add)\s+(.+?)(?:\s+(?:vao|thuoc|trong|to)\s+(.+))?$", folded)
        if not match:
            return {"status": "ask_clarification", "message": "Hay noi ro node can them va vi tri cha.", "action": "add_node"}
        name = match.group(1).strip()
        parent_text = (match.group(2) or "").strip()
        parent = _find_folder_node(db, parent_text) if parent_text else None
        if parent_text and not parent:
            return {"status": "ask_clarification", "message": "Khong tim thay node cha. Hay chon node cha cu the.", "action": "add_node", "name": name}
        node_type = "course"
        if any(token in _fold(name) for token in ("khoa ", "faculty")):
            node_type = "faculty"
        elif any(token in _fold(name) for token in ("chuyen mon", "chuyen nganh", "nhom")):
            node_type = "specialization"
        elif parent and parent["type"] == "course":
            node_type = "standard_folder"
        return {"status": "need_confirmation", "action": "add_node", "name": name, "node_type": node_type, "parent_id": parent["id"] if parent else None}

    return {"status": "ask_clarification", "message": "Yeu cau con mo ho. Hay noi ro hanh dong: them, di chuyen, doi ten, xoa, cap nhat quyen hoac noi luu."}


def preview_policy_action(db, actor: dict, command: str) -> dict:
    action = parse_policy_command(db, command)
    request_id = _id("pcr")
    preview = {
        "status": action["status"],
        "action": action,
        "intent": action.get("action"),
        "understood": action.get("message") or _action_summary(db, action) if action.get("action") else action.get("message", ""),
        "tree_changes": action if action.get("action") in {"add_node", "move_node", "rename_node", "delete_node"} else {},
        "permission_changes": action if action.get("action") in {"update_permission", "update_storage_rule"} else {},
        "warnings": [],
    }
    if action["status"] == "need_confirmation":
        preview["summary"] = _action_summary(db, action)
    db.execute(
        "INSERT INTO policy_change_requests(id,actor_code,command,action_json,preview_json,status,created_at) VALUES(?,?,?,?,?,?,?)",
        (request_id, actor["code"], command, _json(action), _json(preview), action["status"], now()),
    )
    return {"request_id": request_id, **preview}


def _action_summary(db, action: dict) -> str:
    kind = action.get("action")
    if kind == "add_node":
        parent = db.execute("SELECT name FROM folder_nodes WHERE id=?", (action.get("parent_id"),)).fetchone() if action.get("parent_id") else None
        return f"Them node '{action.get('name')}' vao '{parent['name'] if parent else 'root'}'."
    if kind == "rename_node":
        node = db.execute("SELECT name FROM folder_nodes WHERE id=?", (action.get("node_id"),)).fetchone()
        return f"Doi ten '{node['name'] if node else action.get('node_id')}' thanh '{action.get('new_name')}'."
    if kind == "move_node":
        return "Di chuyen node sang node cha moi."
    if kind == "delete_node":
        return f"Deprecated node '{action.get('node_name') or action.get('node_id')}' va cac node con."
    if kind == "update_permission":
        return "Cap nhat rule phan quyen."
    if kind == "update_storage_rule":
        return "Cap nhat rule goi y noi luu."
    return "Yeu cau can xac nhan."


def apply_policy_action(db, actor: dict, action: dict, *, source: str = "api") -> dict:
    if action.get("status") not in {"need_confirmation", "ready"}:
        raise ValueError(action.get("message") or "Action chua san sang de apply.")
    kind = action.get("action")
    if kind not in ACTION_TYPES:
        raise ValueError("Action policy khong duoc ho tro.")
    before = {"action": action, "source": source}
    if kind == "add_node":
        result = create_policy_node(db, actor, action)
    elif kind == "rename_node":
        result = update_policy_node(db, actor, action["node_id"], {"name": action["new_name"]})
    elif kind == "move_node":
        result = update_policy_node(db, actor, action["node_id"], {"parent_id": action["new_parent_id"]})
    elif kind == "delete_node":
        result = delete_policy_node(db, actor, action["node_id"])
    elif kind == "update_permission":
        result = create_policy_rule(db, actor, {"rule_type": "permission", "scope_type": action.get("scope_type", "faculty"), "scope_id": action.get("scope_id"), "value": action.get("value", {})})
    else:
        result = create_policy_rule(db, actor, {"rule_type": "storage_rule", "scope_type": action.get("scope_type", "faculty"), "scope_id": action.get("scope_id"), "value": action.get("value", {})})
    policy_audit(db, actor, f"policy.action.{kind}", "policy_action", result.get("id"), before, result, "success", source)
    return {"status": "applied", "action": kind, "result": result}


def confirm_policy_request(db, actor: dict, request_id: str) -> dict:
    row = db.execute("SELECT * FROM policy_change_requests WHERE id=? AND actor_code=?", (request_id, actor["code"])).fetchone()
    if not row:
        raise ValueError("Khong tim thay preview request.")
    if row["status"] not in {"need_confirmation", "ready"}:
        raise ValueError("Request nay chua du dieu kien confirm.")
    action = _load(row["action_json"])
    dispatch_policy_action_to_n8n(db, actor, request_id, action)
    result = apply_policy_action(db, actor, action, source="confirm")
    timestamp = now()
    db.execute("UPDATE policy_change_requests SET status='applied',confirmed_at=?,applied_at=? WHERE id=?", (timestamp, timestamp, request_id))
    return {"request_id": request_id, **result}


def dispatch_policy_action_to_n8n(db, actor: dict, request_id: str, action: dict) -> dict:
    payload = {"request_id": request_id, "actor": actor["code"], "action": action}
    url = os.getenv("N8N_POLICY_WEBHOOK_URL", "").strip()
    if not url:
        status = "skipped"
        detail = "N8N_POLICY_WEBHOOK_URL is not configured."
    else:
        try:
            request = urllib.request.Request(url, data=_json(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=5) as response:
                detail = response.read().decode("utf-8", errors="ignore")[:1000]
            status = "sent"
        except Exception as exc:
            status = "failed"
            detail = str(exc)
    event_id = _id("evt")
    db.execute(
        "INSERT INTO outbox_events(id,event_type,aggregate_id,payload,status,attempts,created_at,published_at) VALUES(?,?,?,?,?,?,?,?)",
        (event_id, "policy.action.n8n", request_id, _json({**payload, "n8n": {"status": status, "detail": detail}}), status, 1, now(), now()),
    )
    return {"status": status, "detail": detail}


def policy_storage_rule_suggestion(db, text: str) -> dict | None:
    folded = _fold(text)
    for rule in rows(db.execute("SELECT * FROM policy_rules WHERE rule_type='storage_rule' AND status='active' ORDER BY updated_at DESC").fetchall()):
        value = _load(rule["value_json"])
        document_type = value.get("document_type") or rule.get("scope_id")
        if document_type and _fold(str(document_type)) not in folded:
            continue
        folder_node_id = value.get("folder_node_id")
        if folder_node_id:
            node = db.execute("SELECT * FROM folder_nodes WHERE id=? AND status='active'", (folder_node_id,)).fetchone()
            if node:
                return {"folder_node_id": node["id"], "folder_path": node["path"], "document_type": node["name"], "confidence": 0.8}
    return None
