import sqlite3
import json
from contextlib import contextmanager
from typing import Generator, List, Dict, Any, Optional
from datetime import datetime, timezone
from app.config import DB_PATH

def get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT,
            is_admin INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS passkeys (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            public_key TEXT NOT NULL,
            sign_count INTEGER DEFAULT 0,
            transports TEXT DEFAULT '[]',
            device_name TEXT,
            aaguid TEXT,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            category TEXT DEFAULT '通用',
            status TEXT DEFAULT '在用',
            description TEXT DEFAULT '',
            parent_id TEXT,
            primary_image_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES assets(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS asset_images (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT,
            file_size INTEGER DEFAULT 0,
            mime_type TEXT,
            is_primary INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS id_translations (
            prefix TEXT PRIMARY KEY,
            name_prefix TEXT NOT NULL,
            example_id TEXT,
            example_name TEXT,
            is_system INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_assets_location ON assets(location);
        CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);
        CREATE INDEX IF NOT EXISTS idx_assets_category ON assets(category);
        CREATE INDEX IF NOT EXISTS idx_asset_images_asset ON asset_images(asset_id);
        CREATE INDEX IF NOT EXISTS idx_passkeys_user ON passkeys(user_id);
        CREATE INDEX IF NOT EXISTS idx_id_translations_prefix ON id_translations(prefix);
        """)

        # Migration: Check if parent_id column exists for existing tables
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(assets)")
        columns = [row["name"] for row in cur.fetchall()]
        if "parent_id" not in columns:
            conn.execute("ALTER TABLE assets ADD COLUMN parent_id TEXT REFERENCES assets(id) ON DELETE SET NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_parent ON assets(parent_id)")

        # Populate built-in translations if table is empty
        cur.execute("SELECT COUNT(*) as cnt FROM id_translations")
        if cur.fetchone()["cnt"] == 0:
            now = get_now_iso()
            from app.translator import DEFAULT_TRANSLATIONS
            defaults = [
                (prefix, name, f"{prefix}001", f"{name} 001", 1, now)
                for prefix, name in DEFAULT_TRANSLATIONS.items()
            ]
            cur.executemany("""
                INSERT OR IGNORE INTO id_translations (prefix, name_prefix, example_id, example_name, is_system, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, defaults)

def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)

def rows_to_list(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]

