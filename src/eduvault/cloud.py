from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet

from .database import now


ROOT = Path(__file__).resolve().parents[2]


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

PROVIDERS = {
    "google_drive": {
        "label": "Google Drive",
        "client_id": "GOOGLE_CLIENT_ID",
        "client_secret": "GOOGLE_CLIENT_SECRET",
        "redirect_uri": "GOOGLE_REDIRECT_URI",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "openid email https://www.googleapis.com/auth/drive.file",
    },
    "onedrive": {
        "label": "OneDrive",
        "client_id": "MICROSOFT_CLIENT_ID",
        "client_secret": "MICROSOFT_CLIENT_SECRET",
        "redirect_uri": "MICROSOFT_REDIRECT_URI",
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scope": "openid email offline_access Files.ReadWrite",
    },
}


def provider_status(provider: str) -> dict:
    config = PROVIDERS[provider]
    required = ("client_id", "client_secret", "redirect_uri")
    return {
        "provider": provider,
        "label": config["label"],
        "configured": all(os.getenv(config[key], "").strip() for key in required)
        and bool(os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()),
    }


def _cipher() -> Fernet:
    secret = os.getenv("TOKEN_ENCRYPTION_KEY", "eduvault-demo-key-change-before-production")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _protect(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode() if value else ""


def _unprotect(value: str) -> str:
    return _cipher().decrypt(value.encode()).decode() if value else ""


def authorization_url(db, user_code: str, provider: str) -> str:
    config = PROVIDERS[provider]
    if not provider_status(provider)["configured"]:
        raise ValueError(f"{config['label']} chưa được quản trị viên cấu hình OAuth.")
    state = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO oauth_states(state,user_code,provider,created_at) VALUES(?,?,?,?)",
        (state, user_code, provider, now()),
    )
    params = {
        "client_id": os.getenv(config["client_id"]),
        "redirect_uri": os.getenv(config["redirect_uri"]),
        "response_type": "code",
        "scope": config["scope"],
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{config['authorize_url']}?{urllib.parse.urlencode(params)}"


def exchange_code(db, provider: str, state: str, code: str) -> dict:
    state_row = db.execute(
        "SELECT * FROM oauth_states WHERE state=? AND provider=?", (state, provider)
    ).fetchone()
    if not state_row:
        raise ValueError("Phiên kết nối OAuth không hợp lệ hoặc đã hết hạn.")
    config = PROVIDERS[provider]
    token = _post_form(
        config["token_url"],
        {
            "client_id": os.getenv(config["client_id"]),
            "client_secret": os.getenv(config["client_secret"]),
            "redirect_uri": os.getenv(config["redirect_uri"]),
            "grant_type": "authorization_code",
            "code": code,
        },
    )
    email = _email_from_id_token(token.get("id_token", "")) or "Đã xác thực"
    timestamp = now()
    db.execute(
        """INSERT INTO cloud_connections(user_code,provider,account_email,access_token,refresh_token,expires_in,status,created_at,updated_at)
           VALUES(?,?,?,?,?,?,'connected',?,?)
           ON CONFLICT(user_code,provider) DO UPDATE SET
             account_email=excluded.account_email,access_token=excluded.access_token,
             refresh_token=excluded.refresh_token,expires_in=excluded.expires_in,
             status='connected',updated_at=excluded.updated_at""",
        (
            state_row["user_code"], provider, email, _protect(token.get("access_token", "")),
            _protect(token.get("refresh_token", "")), int(token.get("expires_in", 0)), timestamp, timestamp,
        ),
    )
    db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
    return {"user_code": state_row["user_code"], "provider": provider, "account_email": email, "status": "connected"}


def disconnect(db, user_code: str, provider: str) -> None:
    db.execute("DELETE FROM cloud_connections WHERE user_code=? AND provider=?", (user_code, provider))


def list_connections(db, user_code: str) -> list[dict]:
    existing = {
        row["provider"]: dict(row)
        for row in db.execute(
            "SELECT provider,account_email,status,last_sync_at,last_error FROM cloud_connections WHERE user_code=?",
            (user_code,),
        ).fetchall()
    }
    return [
        {
            **provider_status(provider),
            "connected": provider in existing and existing[provider]["status"] == "connected",
            "account_email": existing.get(provider, {}).get("account_email"),
            "last_sync_at": existing.get(provider, {}).get("last_sync_at"),
            "last_error": existing.get(provider, {}).get("last_error"),
        }
        for provider in PROVIDERS
    ]


def sync_user_document(db, user_code: str, document_id: str, source: Path, provider: str | None = None) -> list[dict]:
    query = "SELECT * FROM cloud_connections WHERE user_code=? AND status='connected'"
    params: tuple = (user_code,)
    if provider:
        query += " AND provider=?"
        params = (user_code, provider)
    results = []
    for connection in db.execute(query, params).fetchall():
        try:
            remote = _upload(db, connection, document_id, source)
            timestamp = now()
            db.execute(
                "UPDATE cloud_connections SET last_sync_at=?,last_error=NULL,updated_at=? WHERE user_code=? AND provider=?",
                (timestamp, timestamp, user_code, connection["provider"]),
            )
            db.execute(
                "INSERT INTO cloud_sync_logs(id,user_code,provider,document_id,status,detail,created_at) VALUES(?,?,?,?,?,?,?)",
                (f"cloud-{secrets.token_hex(6)}", user_code, connection["provider"], document_id, "success", remote, timestamp),
            )
            results.append({"provider": connection["provider"], "status": "success", "remote": remote})
        except Exception as exc:
            timestamp = now()
            db.execute(
                "UPDATE cloud_connections SET last_error=?,updated_at=? WHERE user_code=? AND provider=?",
                (str(exc), timestamp, user_code, connection["provider"]),
            )
            db.execute(
                "INSERT INTO cloud_sync_logs(id,user_code,provider,document_id,status,detail,created_at) VALUES(?,?,?,?,?,?,?)",
                (f"cloud-{secrets.token_hex(6)}", user_code, connection["provider"], document_id, "failed", str(exc), timestamp),
            )
            results.append({"provider": connection["provider"], "status": "failed", "detail": str(exc)})
    return results


def _upload(db, connection, document_id: str, source: Path) -> str:
    token = _unprotect(connection["access_token"])
    try:
        return _upload_with_token(connection["provider"], token, document_id, source)
    except urllib.error.HTTPError as exc:
        if exc.code != 401 or not connection["refresh_token"]:
            raise
        token = _refresh_access_token(connection["provider"], _unprotect(connection["refresh_token"]))
        db.execute(
            "UPDATE cloud_connections SET access_token=?,updated_at=? WHERE user_code=? AND provider=?",
            (_protect(token), now(), connection["user_code"], connection["provider"]),
        )
        return _upload_with_token(connection["provider"], token, document_id, source)


def _upload_with_token(provider: str, token: str, document_id: str, source: Path) -> str:
    if provider == "google_drive":
        boundary = f"eduvault-{secrets.token_hex(8)}"
        metadata = json.dumps({"name": f"{document_id}-{source.name}", "appProperties": {"eduvault_document_id": document_id}})
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode() + source.read_bytes() + f"\r\n--{boundary}--".encode()
        data = _authorized_request(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            token, body, f"multipart/related; boundary={boundary}", "POST",
        )
        return f"google-drive:{data.get('id', 'uploaded')}"
    remote_name = urllib.parse.quote(f"EduVault/{document_id}/{source.name}", safe="/")
    data = _authorized_request(
        f"https://graph.microsoft.com/v1.0/me/drive/root:/{remote_name}:/content",
        token, source.read_bytes(), "application/octet-stream", "PUT",
    )
    return data.get("webUrl", f"onedrive:{data.get('id', 'uploaded')}")


def _refresh_access_token(provider: str, refresh_token: str) -> str:
    config = PROVIDERS[provider]
    token = _post_form(
        config["token_url"],
        {
            "client_id": os.getenv(config["client_id"]),
            "client_secret": os.getenv(config["client_secret"]),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": config["scope"],
        },
    )
    return token["access_token"]


def _authorized_request(url: str, token: str, body: bytes, content_type: str, method: str) -> dict:
    request = urllib.request.Request(
        url, data=body, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


def _post_form(url: str, values: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def _email_from_id_token(token: str) -> str:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode())
        return claims.get("email") or claims.get("preferred_username", "")
    except (ValueError, IndexError, json.JSONDecodeError):
        return ""
