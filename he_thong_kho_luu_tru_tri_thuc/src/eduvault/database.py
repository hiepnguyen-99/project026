from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "mvp"
DB_PATH = DATA_DIR / "eduvault.db"
STORAGE_DIR = DATA_DIR / "storage"
BACKUP_DIR = DATA_DIR / "backups"
_ACTIVE_PROVIDER: str | None = None

def load_env_file() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


def database_backend() -> str:
    return _ACTIVE_PROVIDER or os.getenv("DATABASE_PROVIDER", "sqlite").strip().lower()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MySQLConnection:
    def __init__(self):
        import pymysql
        self.raw = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "eduvault"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "eduvault"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    def execute(self, sql: str, params=()):
        sql = sql.replace("INSERT OR IGNORE", "INSERT IGNORE")
        sql = sql.replace("policies(key,value,updated_at)", "policies(`key`,value,updated_at)")
        sql = re.sub(r"\bWHERE key=", "WHERE `key`=", sql)
        sql = re.sub(
            r"ON CONFLICT\(([^)]+)\) DO UPDATE SET\s+(.+)$",
            lambda match: "ON DUPLICATE KEY UPDATE " + re.sub(
                r"excluded\.([A-Za-z_]+)", r"VALUES(\1)", match.group(2)
            ),
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        sql = sql.replace("?", "%s")
        cursor = self.raw.cursor()
        cursor.execute(sql, params)
        return cursor

    def executescript(self, script: str):
        cursor = self.raw.cursor()
        for statement in script.split(";"):
            if statement.strip():
                cursor.execute(statement)
        return cursor

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def connect():
    global _ACTIVE_PROVIDER
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    configured = os.getenv("DATABASE_PROVIDER", "sqlite").strip().lower()
    if configured == "mysql" and _ACTIVE_PROVIDER != "sqlite-fallback":
        try:
            connection = MySQLConnection()
            _ACTIVE_PROVIDER = "mysql"
            return connection
        except Exception:
            allow_fallback = os.getenv("DATABASE_FALLBACK_SQLITE", "true").strip().lower() in {"1", "true", "yes", "on"}
            if not allow_fallback:
                raise
            _ACTIVE_PROVIDER = "sqlite-fallback"
    elif configured != "mysql":
        _ACTIVE_PROVIDER = "sqlite"
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


@contextmanager
def connection():
    db = connect()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction():
    db = connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  code TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
  department TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_code TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(user_code) REFERENCES users(code)
);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, doc_type TEXT NOT NULL, topic TEXT NOT NULL,
  owner_code TEXT NOT NULL, visibility TEXT NOT NULL, current_version INTEGER NOT NULL,
  content_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY(owner_code) REFERENCES users(code)
);
CREATE TABLE IF NOT EXISTS versions (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version_no INTEGER NOT NULL,
  storage_path TEXT NOT NULL, content_hash TEXT NOT NULL, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(document_id, version_no),
  FOREIGN KEY(document_id) REFERENCES documents(id), FOREIGN KEY(created_by) REFERENCES users(code)
);
CREATE TABLE IF NOT EXISTS file_assets (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version_no INTEGER NOT NULL,
  original_name TEXT NOT NULL, original_path TEXT NOT NULL, mime_type TEXT NOT NULL,
  size INTEGER NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id)
);
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version_no INTEGER NOT NULL,
  content TEXT NOT NULL, vector TEXT NOT NULL, provider TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id)
);
CREATE TABLE IF NOT EXISTS access_requests (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, requester_code TEXT NOT NULL,
  owner_code TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT,
  UNIQUE(document_id, requester_code, status)
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor_code TEXT NOT NULL, action TEXT NOT NULL,
  resource_type TEXT NOT NULL, resource_id TEXT, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backup_logs (
  id TEXT PRIMARY KEY, storage_path TEXT NOT NULL, status TEXT NOT NULL,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
  code TEXT PRIMARY KEY, name TEXT NOT NULL, required_doc_types TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transfers (
  id TEXT PRIMARY KEY, course_code TEXT NOT NULL, from_code TEXT NOT NULL,
  to_code TEXT NOT NULL, deadline TEXT NOT NULL, status TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  FOREIGN KEY(course_code) REFERENCES courses(code)
);
CREATE TABLE IF NOT EXISTS external_storages (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
  location TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  last_sync_at TEXT, last_status TEXT NOT NULL DEFAULT 'never'
);
CREATE TABLE IF NOT EXISTS sync_logs (
  id TEXT PRIMARY KEY, storage_id TEXT NOT NULL, document_id TEXT,
  status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(storage_id) REFERENCES external_storages(id)
);
CREATE TABLE IF NOT EXISTS cloud_connections (
  user_code TEXT NOT NULL, provider TEXT NOT NULL, account_email TEXT NOT NULL,
  access_token TEXT NOT NULL, refresh_token TEXT NOT NULL, expires_in INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'connected', last_sync_at TEXT, last_error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(user_code, provider),
  FOREIGN KEY(user_code) REFERENCES users(code)
);
CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY, user_code TEXT NOT NULL, provider TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(user_code) REFERENCES users(code)
);
CREATE TABLE IF NOT EXISTS cloud_sync_logs (
  id TEXT PRIMARY KEY, user_code TEXT NOT NULL, provider TEXT NOT NULL, document_id TEXT NOT NULL,
  status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(user_code) REFERENCES users(code), FOREIGN KEY(document_id) REFERENCES documents(id)
);
CREATE TABLE IF NOT EXISTS document_v2_state (
  document_id TEXT PRIMARY KEY, classification TEXT NOT NULL DEFAULT 'private',
  lifecycle_status TEXT NOT NULL DEFAULT 'published', scan_status TEXT NOT NULL DEFAULT 'clean',
  extraction_status TEXT NOT NULL DEFAULT 'completed', indexing_status TEXT NOT NULL DEFAULT 'completed',
  publish_after TEXT, updated_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id)
);
CREATE TABLE IF NOT EXISTS object_refs (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version_no INTEGER NOT NULL,
  kind TEXT NOT NULL, provider TEXT NOT NULL, object_uri TEXT NOT NULL,
  object_version TEXT NOT NULL DEFAULT '', checksum TEXT NOT NULL, size INTEGER NOT NULL,
  content_type TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id)
);
CREATE TABLE IF NOT EXISTS outbox_events (
  id TEXT PRIMARY KEY, event_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
  payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, published_at TEXT
);
"""

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  code VARCHAR(30) PRIMARY KEY, name VARCHAR(120) NOT NULL, role VARCHAR(30) NOT NULL,
  department VARCHAR(120) NOT NULL, password_hash VARCHAR(64) NOT NULL, active TINYINT NOT NULL DEFAULT 1
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS sessions (
  token VARCHAR(128) PRIMARY KEY, user_code VARCHAR(30) NOT NULL, created_at VARCHAR(40) NOT NULL,
  FOREIGN KEY(user_code) REFERENCES users(code)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS documents (
  id VARCHAR(64) PRIMARY KEY, title VARCHAR(200) NOT NULL, doc_type VARCHAR(80) NOT NULL, topic VARCHAR(120) NOT NULL,
  owner_code VARCHAR(30) NOT NULL, visibility VARCHAR(20) NOT NULL, current_version INT NOT NULL,
  content_hash VARCHAR(64) NOT NULL, created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
  folder_path VARCHAR(1000) NOT NULL DEFAULT '', deleted_at VARCHAR(40) NULL,
  INDEX idx_documents_hash(content_hash), FOREIGN KEY(owner_code) REFERENCES users(code)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS versions (
  id VARCHAR(64) PRIMARY KEY, document_id VARCHAR(64) NOT NULL, version_no INT NOT NULL,
  storage_path TEXT NOT NULL, content_hash VARCHAR(64) NOT NULL, created_by VARCHAR(30) NOT NULL,
  created_at VARCHAR(40) NOT NULL, UNIQUE KEY uq_version(document_id, version_no),
  FOREIGN KEY(document_id) REFERENCES documents(id), FOREIGN KEY(created_by) REFERENCES users(code)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS file_assets (
  id VARCHAR(64) PRIMARY KEY, document_id VARCHAR(64) NOT NULL, version_no INT NOT NULL,
  original_name TEXT NOT NULL, original_path TEXT NOT NULL, mime_type VARCHAR(255) NOT NULL,
  size BIGINT NOT NULL, created_at VARCHAR(40) NOT NULL, FOREIGN KEY(document_id) REFERENCES documents(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS chunks (
  id VARCHAR(64) PRIMARY KEY, document_id VARCHAR(64) NOT NULL, version_no INT NOT NULL,
  content LONGTEXT NOT NULL, vector LONGTEXT NOT NULL, provider VARCHAR(80) NOT NULL, created_at VARCHAR(40) NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS access_requests (
  id VARCHAR(64) PRIMARY KEY, document_id VARCHAR(64) NOT NULL, requester_code VARCHAR(30) NOT NULL,
  owner_code VARCHAR(30) NOT NULL, status VARCHAR(30) NOT NULL, created_at VARCHAR(40) NOT NULL, resolved_at VARCHAR(40),
  UNIQUE KEY uq_access_request(document_id, requester_code, status)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT, actor_code VARCHAR(30) NOT NULL, action VARCHAR(100) NOT NULL,
  resource_type VARCHAR(80) NOT NULL, resource_id VARCHAR(128), detail LONGTEXT NOT NULL, created_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS policies ( `key` VARCHAR(100) PRIMARY KEY, value LONGTEXT NOT NULL, updated_at VARCHAR(40) NOT NULL ) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS backup_logs ( id VARCHAR(64) PRIMARY KEY, storage_path TEXT NOT NULL, status VARCHAR(30) NOT NULL, created_by VARCHAR(30) NOT NULL, created_at VARCHAR(40) NOT NULL ) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS courses ( code VARCHAR(30) PRIMARY KEY, name VARCHAR(200) NOT NULL, required_doc_types LONGTEXT NOT NULL ) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS transfers (
  id VARCHAR(64) PRIMARY KEY, course_code VARCHAR(30) NOT NULL, from_code VARCHAR(30) NOT NULL, to_code VARCHAR(30) NOT NULL,
  deadline VARCHAR(40) NOT NULL, status VARCHAR(30) NOT NULL, progress INT NOT NULL DEFAULT 0, created_at VARCHAR(40) NOT NULL,
  FOREIGN KEY(course_code) REFERENCES courses(code)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS external_storages ( id VARCHAR(64) PRIMARY KEY, name VARCHAR(200) NOT NULL, provider VARCHAR(80) NOT NULL, location TEXT NOT NULL, enabled TINYINT NOT NULL DEFAULT 1, last_sync_at VARCHAR(40), last_status VARCHAR(30) NOT NULL DEFAULT 'never' ) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS sync_logs ( id VARCHAR(64) PRIMARY KEY, storage_id VARCHAR(64) NOT NULL, document_id VARCHAR(64), status VARCHAR(30) NOT NULL, detail TEXT NOT NULL, created_at VARCHAR(40) NOT NULL, FOREIGN KEY(storage_id) REFERENCES external_storages(id) ) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS cloud_connections ( user_code VARCHAR(30) NOT NULL, provider VARCHAR(80) NOT NULL, account_email VARCHAR(255) NOT NULL, access_token LONGTEXT NOT NULL, refresh_token LONGTEXT NOT NULL, expires_in INT NOT NULL DEFAULT 0, status VARCHAR(30) NOT NULL DEFAULT 'connected', last_sync_at VARCHAR(40), last_error TEXT, created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL, PRIMARY KEY(user_code, provider), FOREIGN KEY(user_code) REFERENCES users(code) ) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS oauth_states ( state VARCHAR(128) PRIMARY KEY, user_code VARCHAR(30) NOT NULL, provider VARCHAR(80) NOT NULL, created_at VARCHAR(40) NOT NULL, FOREIGN KEY(user_code) REFERENCES users(code) ) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS cloud_sync_logs ( id VARCHAR(64) PRIMARY KEY, user_code VARCHAR(30) NOT NULL, provider VARCHAR(80) NOT NULL, document_id VARCHAR(64) NOT NULL, status VARCHAR(30) NOT NULL, detail TEXT NOT NULL, created_at VARCHAR(40) NOT NULL, FOREIGN KEY(user_code) REFERENCES users(code), FOREIGN KEY(document_id) REFERENCES documents(id) ) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS document_v2_state (
  document_id VARCHAR(64) PRIMARY KEY, classification VARCHAR(30) NOT NULL DEFAULT 'private',
  lifecycle_status VARCHAR(30) NOT NULL DEFAULT 'published', scan_status VARCHAR(30) NOT NULL DEFAULT 'clean',
  extraction_status VARCHAR(30) NOT NULL DEFAULT 'completed', indexing_status VARCHAR(30) NOT NULL DEFAULT 'completed',
  publish_after VARCHAR(40), updated_at VARCHAR(40) NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS object_refs (
  id VARCHAR(64) PRIMARY KEY, document_id VARCHAR(64) NOT NULL, version_no INT NOT NULL,
  kind VARCHAR(30) NOT NULL, provider VARCHAR(40) NOT NULL, object_uri TEXT NOT NULL,
  object_version VARCHAR(255) NOT NULL DEFAULT '', checksum VARCHAR(64) NOT NULL, size BIGINT NOT NULL,
  content_type VARCHAR(255) NOT NULL, created_at VARCHAR(40) NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS outbox_events (
  id VARCHAR(64) PRIMARY KEY, event_type VARCHAR(100) NOT NULL, aggregate_id VARCHAR(64) NOT NULL,
  payload LONGTEXT NOT NULL, status VARCHAR(30) NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0, created_at VARCHAR(40) NOT NULL, published_at VARCHAR(40)
) ENGINE=InnoDB;
"""


SEED_USERS = [
    ("GV001", "Nguyễn Minh Anh", "lecturer", "Công nghệ thông tin"),
    ("GVNEW", "Lê Thu Hà", "new_lecturer", "Công nghệ thông tin"),
    ("TBM01", "Trần Hoàng Nam", "head", "Công nghệ thông tin"),
    ("ADMIN", "Phạm Quỳnh Chi", "admin", "Phòng hệ thống"),
]

SEED_DOCS = [
    ("de-cuong-ai", "Đề cương học phần Trí tuệ nhân tạo", "Đề cương", "Trí tuệ nhân tạo", "GV001", "public",
     "Học phần Trí tuệ nhân tạo gồm tìm kiếm, biểu diễn tri thức, học máy và hệ chuyên gia. Đánh giá quá trình 40%, thi cuối kỳ 60%."),
    ("rag-guide", "Hướng dẫn xây dựng hệ thống RAG", "Học liệu", "Trí tuệ nhân tạo", "TBM01", "public",
     "RAG gồm ingest, chunking, embedding, retrieval, kiểm tra quyền, sinh câu trả lời và trích dẫn nguồn."),
    ("exam-process", "Quy trình xây dựng đề thi cuối kỳ", "Quy trình", "Khảo thí", "TBM01", "private",
     "Quy trình gồm lập ma trận, biên soạn câu hỏi, phản biện chéo, phê duyệt và bàn giao bảo mật."),
]


def init_database() -> None:
    with transaction() as db:
        db.executescript(MYSQL_SCHEMA if database_backend() == "mysql" else SCHEMA)
        if database_backend() != "mysql":
            columns = {row["name"] for row in db.execute("PRAGMA table_info(documents)").fetchall()}
            if "folder_path" not in columns:
                db.execute("ALTER TABLE documents ADD COLUMN folder_path TEXT NOT NULL DEFAULT ''")
            if "deleted_at" not in columns:
                db.execute("ALTER TABLE documents ADD COLUMN deleted_at TEXT")
        for code, name, role, department in SEED_USERS:
            db.execute(
                "INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, ?, 1)",
                (code, name, role, department, hash_secret(code)),
            )
        db.execute(
            "INSERT OR IGNORE INTO policies VALUES ('backup_321', ?, ?)",
            (json.dumps({"copies": 3, "media": 2, "offsite": 1}), now()),
        )
        db.execute(
            "INSERT OR IGNORE INTO policies VALUES ('storage_rules', ?, ?)",
            (json.dumps({"naming": "{department}/{topic}/{doc_type}/{visibility}", "retention_years": 10}, ensure_ascii=False), now()),
        )
        current_storage_policy = db.execute("SELECT value FROM policies WHERE key='storage_rules'").fetchone()
        if current_storage_policy and "{title}" in current_storage_policy["value"]:
            db.execute(
                "UPDATE policies SET value=?,updated_at=? WHERE key='storage_rules'",
                (json.dumps({"naming": "{department}/{topic}/{doc_type}/{visibility}", "retention_years": 10}, ensure_ascii=False), now()),
            )
        db.execute(
            "INSERT OR IGNORE INTO policies VALUES ('permission_rules', ?, ?)",
            (json.dumps({"private_requires_owner_approval": True}), now()),
        )
        db.execute(
            "INSERT OR IGNORE INTO policies VALUES ('ai_prompts', ?, ?)",
            (json.dumps({
                "metadata_instructions": "Phân loại tài liệu học thuật tiếng Việt. Chỉ trả JSON hợp lệ, không markdown.",
                "answer_instructions": "Trả lời bằng tiếng Việt, chỉ dựa trên ngữ cảnh. Nêu tên tài liệu nguồn và không tiết lộ dữ liệu ngoài ngữ cảnh."
            }, ensure_ascii=False), now()),
        )
        db.execute(
            "INSERT OR IGNORE INTO policies VALUES ('exam_publication', ?, ?)",
            (json.dumps({
                "classification_before_exam": "confidential",
                "read_roles_before_exam": ["head"],
                "publish_after_exam": True,
                "public_scope": "authenticated_faculty",
            }, ensure_ascii=False), now()),
        )
        db.execute(
            "INSERT OR IGNORE INTO courses VALUES ('AI101','Trí tuệ nhân tạo',?)",
            (json.dumps(["Đề cương", "Học liệu", "Ngân hàng câu hỏi"], ensure_ascii=False),),
        )
        db.execute(
            "INSERT OR IGNORE INTO courses VALUES ('PY101','Lập trình Python',?)",
            (json.dumps(["Đề cương", "Học liệu", "Slide"], ensure_ascii=False),),
        )
        for storage_id, name, provider in [
            ("local-primary", "Kho chính EduVault", "local"),
            ("google-drive", "Google Drive", "google_drive"),
            ("onedrive", "OneDrive", "onedrive"),
        ]:
            location = str(DATA_DIR / "external" / storage_id)
            Path(location).mkdir(parents=True, exist_ok=True)
            db.execute(
                "INSERT OR IGNORE INTO external_storages(id,name,provider,location,enabled,last_status) VALUES(?,?,?,?,1,'ready')",
                (storage_id, name, provider, location),
            )
        for slug, title, doc_type, topic, owner, visibility, content in SEED_DOCS:
            doc_id = f"doc-{slug}"
            exists = db.execute("SELECT 1 FROM documents WHERE id=?", (doc_id,)).fetchone()
            if exists:
                continue
            doc_dir = STORAGE_DIR / doc_id
            doc_dir.mkdir(parents=True, exist_ok=True)
            path = doc_dir / "v1.txt"
            path.write_text(content, encoding="utf-8")
            digest = hash_secret(content)
            timestamp = now()
            db.execute(
                "INSERT INTO documents(id,title,doc_type,topic,owner_code,visibility,current_version,content_hash,created_at,updated_at,folder_path) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, '')",
                (doc_id, title, doc_type, topic, owner, visibility, digest, timestamp, timestamp),
            )
            db.execute(
                "INSERT INTO versions VALUES (?, ?, 1, ?, ?, ?, ?)",
                (f"ver-{slug}-1", doc_id, str(path), digest, owner, timestamp),
            )
        for document in db.execute("SELECT id,title,visibility,topic,doc_type FROM documents").fetchall():
            classification = "confidential" if "đề thi" in f"{document['title']} {document['topic']} {document['doc_type']}".lower() else document["visibility"]
            db.execute(
                "INSERT OR IGNORE INTO document_v2_state(document_id,classification,lifecycle_status,scan_status,extraction_status,indexing_status,updated_at) VALUES(?,?,'published','clean','completed','completed',?)",
                (document["id"], classification, now()),
            )


def rows(items) -> list[dict]:
    return [dict(item) for item in items]


SNAPSHOT_TABLES = [
    "users", "sessions", "documents", "versions", "file_assets", "chunks",
    "access_requests", "audit_logs", "policies", "backup_logs", "courses",
    "transfers", "external_storages", "sync_logs", "cloud_connections",
    "oauth_states", "cloud_sync_logs",
    "document_v2_state", "object_refs", "outbox_events",
]


def snapshot_database(db, destination: Path) -> None:
    if database_backend() != "mysql":
        target = sqlite3.connect(destination)
        try:
            db.backup(target)
        finally:
            target.close()
        return
    payload = {table: rows(db.execute(f"SELECT * FROM {table}").fetchall()) for table in SNAPSHOT_TABLES}
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def restore_database(db, source: Path) -> None:
    if database_backend() != "mysql":
        source_db = sqlite3.connect(source)
        try:
            source_db.backup(db)
        finally:
            source_db.close()
        return
    payload = json.loads(source.read_text(encoding="utf-8"))
    db.execute("SET FOREIGN_KEY_CHECKS=0")
    try:
        for table in reversed(SNAPSHOT_TABLES):
            db.execute(f"DELETE FROM {table}")
        for table in SNAPSHOT_TABLES:
            for item in payload.get(table, []):
                columns = list(item)
                placeholders = ",".join("?" for _ in columns)
                quoted = ",".join(f"`{column}`" for column in columns)
                db.execute(
                    f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",
                    tuple(item[column] for column in columns),
                )
    finally:
        db.execute("SET FOREIGN_KEY_CHECKS=1")
