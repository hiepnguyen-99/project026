# MySQL Setup

EduVault stores metadata, users, permissions, chunks and audit logs in MySQL.
Original large files remain in `data/mvp/storage` or configured external/object
storage. This avoids placing large BLOBs inside MySQL and keeps backup/restore
manageable.

## Start MySQL

```powershell
docker compose -f docker-compose.mysql.yml up -d
pip install -r requirements.txt
```

Add these values to `.env`:

```text
DATABASE_PROVIDER=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
MYSQL_DATABASE=eduvault
MYSQL_USER=eduvault
MYSQL_PASSWORD=change-me
MAX_UPLOAD_MB=250
```

## Migrate Existing SQLite Metadata

Stop the backend first, then run:

```powershell
python scripts/migrate_sqlite_to_mysql.py --replace
```

Start the backend:

```powershell
python run_mvp.py
```

## Large Files

`MAX_UPLOAD_MB` controls the API upload limit. MySQL's container is configured
with `max_allowed_packet=512M`, but file binaries are intentionally stored on
filesystem/object storage rather than in database rows.
