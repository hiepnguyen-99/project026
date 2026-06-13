from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate EduVault metadata from SQLite to MySQL.")
    parser.add_argument("--source", default=str(ROOT / "data" / "mvp" / "eduvault.db"))
    parser.add_argument("--replace", action="store_true", help="Clear MySQL tables before importing.")
    args = parser.parse_args()

    os.environ["DATABASE_PROVIDER"] = "mysql"
    from src.eduvault.database import SNAPSHOT_TABLES, connect, init_database

    source_path = Path(args.source).resolve()
    if not source_path.exists():
        raise SystemExit(f"SQLite source not found: {source_path}")

    init_database()
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = connect()
    try:
        target.execute("SET FOREIGN_KEY_CHECKS=0")
        if args.replace:
            for table in reversed(SNAPSHOT_TABLES):
                target.execute(f"DELETE FROM {table}")
        for table in SNAPSHOT_TABLES:
            exists = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            for row in source.execute(f"SELECT * FROM {table}").fetchall():
                item = dict(row)
                columns = list(item)
                placeholders = ",".join("?" for _ in columns)
                quoted = ",".join(f"`{column}`" for column in columns)
                target.execute(
                    f"INSERT IGNORE INTO {table} ({quoted}) VALUES ({placeholders})",
                    tuple(item[column] for column in columns),
                )
        target.execute("SET FOREIGN_KEY_CHECKS=1")
        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()
    print(f"Migrated EduVault metadata from {source_path} to MySQL.")


if __name__ == "__main__":
    main()
