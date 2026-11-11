from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.auth import get_current_user, generate_reg_options
from app.database import get_db, rows_to_list
from app.models import RenamePasskeyRequest

router = APIRouter(prefix="/api/user", tags=["user"])

@router.get("/me")
def get_user_profile(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT id, device_name, aaguid, created_at, last_used_at, transports
            FROM passkeys
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user["id"],),
        )
        passkeys = rows_to_list(cursor.fetchall())

    return {
        "user": user,
        "passkeys": passkeys,
    }

@router.get("/passkeys/add-options")
def get_add_passkey_options(request: Request, user: dict = Depends(get_current_user)):
    return generate_reg_options(
        request=request,
        user_id=user["id"],
        username=user["username"],
        display_name=user.get("display_name") or user["username"],
        exclude_existing=True,
    )

@router.post("/passkeys/rename")
def rename_passkey(req: RenamePasskeyRequest, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM passkeys WHERE id = ? AND user_id = ?",
            (req.passkey_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到该凭据")

        conn.execute(
            "UPDATE passkeys SET device_name = ? WHERE id = ?",
            (req.device_name.strip(), req.passkey_id),
        )
    return {"success": True, "message": "设备名称更新成功"}

@router.delete("/passkeys/{passkey_id}")
def delete_passkey(passkey_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        # Check total passkeys count for this user
        count_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM passkeys WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
        if count_row["cnt"] <= 1:
            raise HTTPException(
                status_code=400,
                detail="无法删除唯一的 Passkey！请先添加至少另一个备用 Passkey 凭据以防失联。",
            )

        deleted = conn.execute(
            "DELETE FROM passkeys WHERE id = ? AND user_id = ?",
            (passkey_id, user["id"]),
        ).rowcount
        if deleted == 0:
            raise HTTPException(status_code=404, detail="未找到该凭据")

    return {"success": True, "message": "Passkey 凭据已成功移除"}

