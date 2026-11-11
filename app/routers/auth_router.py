import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status

from app.database import get_db, row_to_dict
from app.config import (
    SESSION_COOKIE_NAME,
    SESSION_EXPIRE_DAYS,
    get_effective_rp_id,
    get_effective_origin,
)
from app.auth import (
    generate_reg_options,
    verify_reg_response,
    generate_auth_options,
    verify_auth_response,
    create_session_token,
    get_current_user_optional,
    get_current_user,
)
from app.models import (
    RegisterOptionsRequest,
    RegisterVerifyRequest,
    LoginOptionsRequest,
    LoginVerifyRequest,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

def set_auth_cookie(response: Response, token: str):
    max_age = SESSION_EXPIRE_DAYS * 24 * 3600
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # Can be accessed over local HTTP or HTTPS
    )

@router.get("/status")
def get_auth_status(request: Request):
    user = get_current_user_optional(request)
    with get_db() as conn:
        user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        has_users = user_count > 0

    return {
        "has_users": has_users,
        "is_authenticated": user is not None,
        "user": user,
        "rp_id": get_effective_rp_id(request),
        "origin": get_effective_origin(request),
    }

@router.post("/register-options")
def register_options(req: RegisterOptionsRequest, request: Request):
    current_user = get_current_user_optional(request)
    
    with get_db() as conn:
        user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        # If users exist and caller is not logged in, registration is restricted
        if user_count > 0 and not current_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="系统已有管理员，添加新设备或用户必须先登录已授权账号",
            )
        
        # Check if username exists
        target_username = req.username.strip()
        user_row = conn.execute("SELECT id, username, display_name FROM users WHERE username = ?", (target_username,)).fetchone()
        
        if user_row:
            user_id = user_row["id"]
            display_name = user_row["display_name"] or target_username
        else:
            user_id = str(uuid.uuid4())
            display_name = req.display_name.strip() if req.display_name else target_username

    return generate_reg_options(
        request=request,
        user_id=user_id,
        username=target_username,
        display_name=display_name,
        exclude_existing=True,
    )

@router.post("/register-verify")
def register_verify(req: RegisterVerifyRequest, request: Request, response: Response):
    reg_result = verify_reg_response(
        request=request,
        challenge_id=req.challenge_id,
        credential_data=req.credential,
        device_name=req.device_name,
    )

    user_id = reg_result["user_id"]
    username = reg_result["username"]
    display_name = reg_result["display_name"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        # Check if user already exists
        user_row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user_row:
            # First user is admin
            user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            is_admin = 1 if user_count == 0 else 0
            conn.execute(
                """
                INSERT INTO users (id, username, display_name, is_admin, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, display_name, is_admin, now_iso),
            )

        # Insert passkey credential
        conn.execute(
            """
            INSERT INTO passkeys (id, user_id, public_key, sign_count, transports, device_name, aaguid, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reg_result["credential_id"],
                user_id,
                reg_result["public_key"],
                reg_result["sign_count"],
                reg_result["transports"],
                reg_result["device_name"],
                reg_result["aaguid"],
                now_iso,
                now_iso,
            ),
        )

    # Issue session token
    token = create_session_token(user_id, username)
    set_auth_cookie(response, token)

    return {
        "success": True,
        "token": token,
        "user": {
            "id": user_id,
            "username": username,
            "display_name": display_name,
        },
        "message": "Passkey 绑定成功！",
    }

@router.post("/login-options")
def login_options(req: LoginOptionsRequest, request: Request):
    return generate_auth_options(request, username=req.username)

@router.post("/login-verify")
def login_verify(req: LoginVerifyRequest, request: Request, response: Response):
    auth_result = verify_auth_response(
        request=request,
        challenge_id=req.challenge_id,
        credential_data=req.credential,
    )

    token = create_session_token(auth_result["user_id"], auth_result["username"])
    set_auth_cookie(response, token)

    return {
        "success": True,
        "token": token,
        "user": auth_result,
        "message": "Passkey 登录成功！",
    }

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"success": True, "message": "已成功退出登录"}

