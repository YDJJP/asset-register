import os
import secrets
from pathlib import Path
from typing import Optional, List
from fastapi import Request

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
THUMB_DIR = UPLOAD_DIR / "thumbnails"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = str(DATA_DIR / "assets.db")

# Secret key persistence (persisted in data directory if not provided in env)
SECRET_KEY_FILE = DATA_DIR / ".secret_key"
def _get_or_create_secret_key() -> str:
    env_secret = os.getenv("SECRET_KEY")
    if env_secret:
        return env_secret
    if SECRET_KEY_FILE.exists():
        try:
            return SECRET_KEY_FILE.read_text().strip()
        except Exception:
            pass
    new_key = secrets.token_hex(32)
    try:
        SECRET_KEY_FILE.write_text(new_key)
    except Exception:
        pass
    return new_key

SECRET_KEY = _get_or_create_secret_key()
JWT_ALGORITHM = "HS256"
SESSION_COOKIE_NAME = "asset_session"
SESSION_EXPIRE_DAYS = int(os.getenv("SESSION_EXPIRE_DAYS", "30"))

# WebAuthn Configuration
RP_NAME = os.getenv("RP_NAME", "Asset Register (资产登记)")
CONFIG_RP_ID = os.getenv("RP_ID", "").strip() or None
CONFIG_RP_ORIGIN = os.getenv("RP_ORIGIN", "").strip() or None

def get_effective_rp_id(request: Request) -> str:
    """
    Get effective RP_ID. If configured via env, use it.
    Otherwise, extract the hostname from the request Host header.
    """
    if CONFIG_RP_ID:
        return CONFIG_RP_ID
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    # Strip port if present
    return host.split(":")[0]

def get_effective_origin(request: Request) -> str:
    """
    Get effective expected origin. If configured via env, use it.
    Otherwise, extract from Origin or Referer header, or reconstruct from scheme and host.
    """
    if CONFIG_RP_ORIGIN:
        return CONFIG_RP_ORIGIN
    
    # Check origin header first
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    
    # Check referer header
    referer = request.headers.get("referer")
    if referer:
        from urllib.parse import urlparse
        p = urlparse(referer)
        return f"{p.scheme}://{p.netloc}"
    
    # Check X-Forwarded-Proto / Host headers for reverse proxies (e.g. 1Panel OpenResty)
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    return f"{scheme}://{host}"

