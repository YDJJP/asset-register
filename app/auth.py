import time
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

import jwt
from fastapi import Request, HTTPException, status
import webauthn
from webauthn.helpers import (
    options_to_json,
    bytes_to_base64url,
    base64url_to_bytes,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialType,
)

from app.config import (
    SECRET_KEY,
    JWT_ALGORITHM,
    SESSION_COOKIE_NAME,
    SESSION_EXPIRE_DAYS,
    get_effective_rp_id,
    get_effective_origin,
    RP_NAME,
)
from app.database import get_db, row_to_dict

# -------------------------------------------------------------
# In-Memory Challenge Store (Thread-safe dict with TTL cleanup)
# -------------------------------------------------------------
class ChallengeStore:
    def __init__(self, default_ttl: int = 300):
        self._store: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl

    def _cleanup(self):
        now = time.time()
        expired_keys = [k for k, v in self._store.items() if v.get("expires_at", 0) < now]
        for k in expired_keys:
            self._store.pop(k, None)

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        self._cleanup()
        expires_at = time.time() + (ttl or self.default_ttl)
        self._store[key] = {
            "value": value,
            "expires_at": expires_at,
        }

    def pop(self, key: str) -> Optional[Any]:
        self._cleanup()
        item = self._store.pop(key, None)
        if not item:
            return None
        if item.get("expires_at", 0) < time.time():
            return None
        return item.get("value")

challenge_store = ChallengeStore(default_ttl=300)


# -------------------------------------------------------------
# JWT & Session Handling
# -------------------------------------------------------------
def create_session_token(user_id: str, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=SESSION_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "username": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception:
        return None


def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    
    if not token:
        return None

    payload = decode_session_token(token)
    if not payload or not payload.get("sub"):
        return None

    user_id = payload["sub"]
    with get_db() as conn:
        cursor = conn.execute("SELECT id, username, display_name, is_admin, created_at FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return row_to_dict(row)


def get_current_user(request: Request) -> Dict[str, Any]:
    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要登录以访问此资源",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# -------------------------------------------------------------
# WebAuthn Helpers
# -------------------------------------------------------------
def get_user_credentials_descriptors(user_id: str) -> List[PublicKeyCredentialDescriptor]:
    with get_db() as conn:
        cursor = conn.execute("SELECT id FROM passkeys WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        return [
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(r["id"]),
                type=PublicKeyCredentialType.PUBLIC_KEY,
            )
            for r in rows
        ]


def generate_reg_options(
    request: Request,
    user_id: str,
    username: str,
    display_name: str,
    exclude_existing: bool = True,
) -> Dict[str, Any]:
    rp_id = get_effective_rp_id(request)
    user_id_bytes = user_id.encode("utf-8")
    
    exclude_credentials = []
    if exclude_existing:
        exclude_credentials = get_user_credentials_descriptors(user_id)

    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=user_id_bytes,
        user_name=username,
        user_display_name=display_name or username,
        attestation=webauthn.helpers.structs.AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_credentials,
        timeout=60000,
    )

    # Save challenge session
    challenge_id = secrets.token_urlsafe(32)
    challenge_store.set(
        f"reg:{challenge_id}",
        {
            "challenge": options.challenge,
            "user_id": user_id,
            "username": username,
            "display_name": display_name,
            "rp_id": rp_id,
        },
        ttl=300,
    )

    options_dict = json.loads(options_to_json(options))
    return {
        "challenge_id": challenge_id,
        "options": options_dict,
    }


def verify_reg_response(
    request: Request,
    challenge_id: str,
    credential_data: Dict[str, Any],
    device_name: Optional[str] = None,
) -> Dict[str, Any]:
    cached = challenge_store.pop(f"reg:{challenge_id}")
    if not cached:
        raise HTTPException(status_code=400, detail="注册验证超时或会话无效，请重新尝试")

    expected_challenge = cached["challenge"]
    expected_rp_id = cached["rp_id"]
    expected_origin = get_effective_origin(request)

    try:
        verified_reg = webauthn.verify_registration_response(
            credential=credential_data,
            expected_challenge=expected_challenge,
            expected_rp_id=expected_rp_id,
            expected_origin=expected_origin,
            require_user_verification=False,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Passkey 注册验证失败: {str(e)}")

    cred_id_b64 = bytes_to_base64url(verified_reg.credential_id)
    cred_pk_b64 = bytes_to_base64url(verified_reg.credential_public_key)
    
    # Extract transports if sent from browser
    transports = []
    if isinstance(credential_data.get("response"), dict):
        transports = credential_data["response"].get("transports") or []

    return {
        "user_id": cached["user_id"],
        "username": cached["username"],
        "display_name": cached["display_name"],
        "credential_id": cred_id_b64,
        "public_key": cred_pk_b64,
        "sign_count": verified_reg.sign_count,
        "aaguid": verified_reg.aaguid,
        "transports": json.dumps(transports),
        "device_name": device_name or "Passkey 凭据",
    }


def generate_auth_options(request: Request, username: Optional[str] = None) -> Dict[str, Any]:
    rp_id = get_effective_rp_id(request)
    allow_credentials = None

    target_user_id = None
    if username:
        with get_db() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if user_row:
                target_user_id = user_row["id"]
                allow_credentials = get_user_credentials_descriptors(target_user_id)

    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
        timeout=60000,
    )

    challenge_id = secrets.token_urlsafe(32)
    challenge_store.set(
        f"auth:{challenge_id}",
        {
            "challenge": options.challenge,
            "rp_id": rp_id,
            "user_id": target_user_id,
        },
        ttl=300,
    )

    options_dict = json.loads(options_to_json(options))
    return {
        "challenge_id": challenge_id,
        "options": options_dict,
    }


def verify_auth_response(
    request: Request,
    challenge_id: str,
    credential_data: Dict[str, Any],
) -> Dict[str, Any]:
    cached = challenge_store.pop(f"auth:{challenge_id}")
    if not cached:
        raise HTTPException(status_code=400, detail="登录会话已超时，请重新点击登录")

    cred_raw_id = credential_data.get("id")
    if not cred_raw_id:
        raise HTTPException(status_code=400, detail="无效的凭据数据")

    # Look up passkey in DB
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT p.id, p.user_id, p.public_key, p.sign_count, p.device_name,
                   u.username, u.display_name, u.is_admin
            FROM passkeys p
            JOIN users u ON p.user_id = u.id
            WHERE p.id = ?
            """,
            (cred_raw_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="未找到该 Passkey 对应的用户")

        passkey_info = dict(row)

    expected_challenge = cached["challenge"]
    expected_rp_id = cached["rp_id"]
    expected_origin = get_effective_origin(request)
    pub_key_bytes = base64url_to_bytes(passkey_info["public_key"])

    try:
        verified_auth = webauthn.verify_authentication_response(
            credential=credential_data,
            expected_challenge=expected_challenge,
            expected_rp_id=expected_rp_id,
            expected_origin=expected_origin,
            credential_public_key=pub_key_bytes,
            credential_current_sign_count=passkey_info["sign_count"],
            require_user_verification=False,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Passkey 登录验证失败: {str(e)}")

    # Update sign count and last_used_at in DB
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE passkeys SET sign_count = ?, last_used_at = ? WHERE id = ?",
            (verified_auth.new_sign_count, now_iso, cred_raw_id),
        )

    return {
        "user_id": passkey_info["user_id"],
        "username": passkey_info["username"],
        "display_name": passkey_info["display_name"],
        "is_admin": passkey_info["is_admin"],
    }

