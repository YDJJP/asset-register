import io
import os
import csv
import uuid
from typing import Optional, List
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Query,
    Response,
    status,
)
from PIL import Image, ImageOps

from app.auth import get_current_user
from app.config import UPLOAD_DIR, THUMB_DIR
from app.database import get_db, rows_to_list, row_to_dict
from app.models import AssetCreateRequest, AssetUpdateRequest, TranslationRuleRequest
from app.recognizer import recognize_asset_id_from_image
from app.translator import translate_asset_id, learn_translation, parse_asset_id

router = APIRouter(prefix="/api/assets", tags=["assets"])

def get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def process_and_save_image(file_bytes: bytes, original_filename: str) -> tuple[str, str, int, str]:
    """
    Processes image with Pillow:
    - Auto-corrects EXIF orientation (critical for smartphone photos)
    - Compresses to 1080p (max 1920x1920 bounding box, quality 82, progressive, optimized)
    - Generates thumbnail (max 400x400, quality 80)
    Returns: (saved_filename, thumb_filename, file_size, mime_type)
    """
    image_id = uuid.uuid4().hex
    saved_filename = f"{image_id}.jpg"
    thumb_filename = f"{image_id}_thumb.jpg"

    full_path = UPLOAD_DIR / saved_filename
    thumb_path = THUMB_DIR / thumb_filename

    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            # Handle orientation
            img = ImageOps.exif_transpose(img)
            
            # Convert RGBA / P to RGB
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # 1080p version (downscale to max 1920 on longest edge, preserving aspect ratio)
            img_full = img.copy()
            img_full.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            img_full.save(full_path, format="JPEG", quality=82, optimize=True, progressive=True)

            # Thumbnail
            img_thumb = img.copy()
            img_thumb.thumbnail((400, 400), Image.Resampling.LANCZOS)
            img_thumb.save(thumb_path, format="JPEG", quality=80, optimize=True)

        file_size = os.path.getsize(full_path)
        return saved_filename, thumb_filename, file_size, "image/jpeg"
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图片解析或保存失败: {str(e)}")


@router.get("")
def list_assets(
    q: Optional[str] = Query(None, description="搜索关键词"),
    location: Optional[str] = Query(None, description="筛选位置"),
    category: Optional[str] = Query(None, description="筛选类别"),
    status: Optional[str] = Query(None, description="筛选状态"),
    parent_id: Optional[str] = Query(None, description="筛选所属父设备编号"),
    hierarchy: Optional[str] = Query(None, description="层级筛选: all, root(仅主设备), children(仅子设备)"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    offset = (page - 1) * limit
    conditions = []
    params = []

    if q:
        query_like = f"%{q.strip()}%"
        conditions.append("(a.id LIKE ? OR a.name LIKE ? OR a.location LIKE ? OR a.description LIKE ? OR p.name LIKE ?)")
        params.extend([query_like, query_like, query_like, query_like, query_like])

    if location and location.strip():
        conditions.append("a.location = ?")
        params.append(location.strip())

    if category and category.strip():
        conditions.append("a.category = ?")
        params.append(category.strip())

    if status and status.strip():
        conditions.append("a.status = ?")
        params.append(status.strip())

    if parent_id and parent_id.strip():
        conditions.append("a.parent_id = ?")
        params.append(parent_id.strip())

    if hierarchy == "root":
        conditions.append("(a.parent_id IS NULL OR a.parent_id = '')")
    elif hierarchy == "children":
        conditions.append("(a.parent_id IS NOT NULL AND a.parent_id != '')")

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    with get_db() as conn:
        # Total count
        count_sql = f"SELECT COUNT(*) as count FROM assets a LEFT JOIN assets p ON a.parent_id = p.id {where_clause}"
        total = conn.execute(count_sql, params).fetchone()["count"]

        # Main query with primary image filename, parent info, and children count
        query_sql = f"""
            SELECT a.id, a.name, a.location, a.category, a.status, a.description,
                   a.parent_id, p.name AS parent_name,
                   a.primary_image_id, a.created_at, a.updated_at,
                   img.filename AS primary_image_filename,
                   (SELECT COUNT(*) FROM asset_images WHERE asset_id = a.id) AS image_count,
                   (SELECT COUNT(*) FROM assets WHERE parent_id = a.id) AS children_count
            FROM assets a
            LEFT JOIN assets p ON a.parent_id = p.id
            LEFT JOIN asset_images img ON a.primary_image_id = img.id
            {where_clause}
            ORDER BY a.updated_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query_sql, params + [limit, offset]).fetchall()
        assets = rows_to_list(rows)

        # Attach image urls
        for item in assets:
            fn = item.pop("primary_image_filename", None)
            if fn:
                item["primary_image_url"] = f"/uploads/{fn}"
                item["primary_thumb_url"] = f"/uploads/thumbnails/{fn.replace('.jpg', '_thumb.jpg')}"
            else:
                item["primary_image_url"] = None
                item["primary_thumb_url"] = None

    return {
        "items": assets,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 1,
    }


@router.post("/recognize-id")
async def recognize_id(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """
    Auto-recognizes Asset ID from an uploaded image (barcodes, QR codes, or OCR text labels),
    and translates ID into human-friendly device name (e.g. CPR001 -> Capper 001, PU.023 -> Pump 023).
    """
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="未收到有效的图片内容")

    result = recognize_asset_id_from_image(contents)
    best_id = result.get("best_id", "")
    with get_db() as conn:
        translated_name, rule = translate_asset_id(best_id, conn)
    result["translated_name"] = translated_name
    result["translation_rule"] = rule
    return result


@router.get("/meta/stats")
def get_stats(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        total_assets = conn.execute("SELECT COUNT(*) as cnt FROM assets").fetchone()["cnt"]
        total_images = conn.execute("SELECT COUNT(*) as cnt FROM asset_images").fetchone()["cnt"]
        total_locations = conn.execute("SELECT COUNT(DISTINCT location) as cnt FROM assets").fetchone()["cnt"]

        status_rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM assets GROUP BY status"
        ).fetchall()
        category_rows = conn.execute(
            "SELECT category, COUNT(*) as count FROM assets GROUP BY category"
        ).fetchall()

    return {
        "total_assets": total_assets,
        "total_images": total_images,
        "total_locations": total_locations,
        "by_status": rows_to_list(status_rows),
        "by_category": rows_to_list(category_rows),
    }


@router.get("/meta/locations")
def get_locations(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT location, COUNT(*) as count
            FROM assets
            WHERE location != ''
            GROUP BY location
            ORDER BY count DESC, location ASC
            """
        ).fetchall()
        return rows_to_list(rows)


@router.get("/meta/parent-options")
def get_parent_options(exclude_id: Optional[str] = Query(None), user: dict = Depends(get_current_user)):
    """
    Returns list of assets for parent device selector dropdown.
    """
    with get_db() as conn:
        if exclude_id:
            rows = conn.execute(
                "SELECT id, name, location, category FROM assets WHERE id != ? ORDER BY id ASC LIMIT 500",
                (exclude_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, location, category FROM assets ORDER BY id ASC LIMIT 500"
            ).fetchall()
        return rows_to_list(rows)


@router.get("/meta/translate")
def get_translation(id: str = Query(..., description="待翻译资产编号"), user: dict = Depends(get_current_user)):
    """
    Translates an ID into human friendly name candidate (e.g. CPR001 -> Capper 001, PU.023 -> Pump 023).
    """
    with get_db() as conn:
        translated, rule = translate_asset_id(id.strip(), conn)
    return {"id": id, "translated_name": translated, "rule": rule}


@router.get("/meta/translations")
def list_translations(user: dict = Depends(get_current_user)):
    """
    Lists all learned and built-in prefix translation rules.
    """
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM id_translations ORDER BY is_system ASC, prefix ASC").fetchall()
        return rows_to_list(rows)


@router.post("/meta/translations")
def upsert_translation(req: TranslationRuleRequest, user: dict = Depends(get_current_user)):
    """
    Manually creates or updates an ID prefix translation rule.
    """
    prefix = req.prefix.strip().upper()
    now = get_now_iso()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO id_translations (prefix, name_prefix, example_id, example_name, is_system, updated_at)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(prefix) DO UPDATE SET
                name_prefix = excluded.name_prefix,
                example_id = excluded.example_id,
                example_name = excluded.example_name,
                updated_at = excluded.updated_at
        """, (prefix, req.name_prefix.strip(), req.example_id or f"{prefix}001", req.example_name or f"{req.name_prefix} 001", now))
    return {"success": True, "prefix": prefix}


@router.delete("/meta/translations/{prefix}")
def delete_translation(prefix: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        conn.execute("DELETE FROM id_translations WHERE prefix = ?", (prefix.strip().upper(),))
    return {"success": True}


@router.get("/{asset_id}")
def get_asset(asset_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到该资产信息")
        asset = dict(row)

        # Get parent device details if linked
        if asset.get("parent_id"):
            p_row = conn.execute(
                "SELECT id, name, location, category, status FROM assets WHERE id = ?",
                (asset["parent_id"],),
            ).fetchone()
            asset["parent"] = dict(p_row) if p_row else None
        else:
            asset["parent"] = None

        # Get child components / sub-devices
        c_rows = conn.execute(
            """
            SELECT a.id, a.name, a.location, a.category, a.status, a.updated_at,
                   img.filename AS primary_image_filename
            FROM assets a
            LEFT JOIN asset_images img ON a.primary_image_id = img.id
            WHERE a.parent_id = ?
            ORDER BY a.id ASC
            """,
            (asset_id,),
        ).fetchall()
        children = rows_to_list(c_rows)
        for c in children:
            fn = c.pop("primary_image_filename", None)
            c["primary_thumb_url"] = f"/uploads/thumbnails/{fn.replace('.jpg', '_thumb.jpg')}" if fn else None
        asset["children"] = children

        # Get all images for this asset
        img_rows = conn.execute(
            """
            SELECT id, asset_id, filename, original_name, file_size, mime_type, is_primary, created_at
            FROM asset_images
            WHERE asset_id = ?
            ORDER BY is_primary DESC, created_at ASC
            """,
            (asset_id,),
        ).fetchall()
        images = rows_to_list(img_rows)

        for img in images:
            fn = img["filename"]
            img["url"] = f"/uploads/{fn}"
            img["thumb_url"] = f"/uploads/thumbnails/{fn.replace('.jpg', '_thumb.jpg')}"

        asset["images"] = images
        return asset


@router.post("")
def create_asset(req: AssetCreateRequest, user: dict = Depends(get_current_user)):
    now = get_now_iso()
    asset_id = req.id.strip()
    parent_id = req.parent_id.strip() if req.parent_id and req.parent_id.strip() else None

    if parent_id and parent_id == asset_id:
        raise HTTPException(status_code=400, detail="设备不能将自身设为所属父设备")

    with get_db() as conn:
        exists = conn.execute("SELECT id FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail=f"资产编号 '{asset_id}' 已存在，请更换！")

        if parent_id:
            p_exists = conn.execute("SELECT id FROM assets WHERE id = ?", (parent_id,)).fetchone()
            if not p_exists:
                raise HTTPException(status_code=400, detail=f"指定的父设备 '{parent_id}' 不存在")

        conn.execute(
            """
            INSERT INTO assets (id, name, location, category, status, description, parent_id, primary_image_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                asset_id,
                req.name.strip(),
                req.location.strip(),
                req.category.strip() if req.category else "通用",
                req.status.strip() if req.status else "在用",
                req.description.strip() if req.description else "",
                parent_id,
                now,
                now,
            ),
        )

        # Smart self-learning: Learn translation mapping from user's input
        learn_translation(asset_id, req.name.strip(), conn)

    return {"success": True, "id": asset_id, "message": "资产创建成功"}


@router.put("/{asset_id}")
def update_asset(asset_id: str, req: AssetUpdateRequest, user: dict = Depends(get_current_user)):
    now = get_now_iso()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="未找到该资产")

        fields = []
        params = []
        if req.name is not None:
            fields.append("name = ?")
            params.append(req.name.strip())
        if req.location is not None:
            fields.append("location = ?")
            params.append(req.location.strip())
        if req.category is not None:
            fields.append("category = ?")
            params.append(req.category.strip())
        if req.status is not None:
            fields.append("status = ?")
            params.append(req.status.strip())
        if req.description is not None:
            fields.append("description = ?")
            params.append(req.description.strip())
        if req.parent_id is not None:
            p_id = req.parent_id.strip() if req.parent_id.strip() else None
            if p_id == asset_id:
                raise HTTPException(status_code=400, detail="不能将设备自身设为父设备")
            if p_id:
                # Circular dependency check: parent cannot be one of current asset's children
                is_child = conn.execute("SELECT id FROM assets WHERE parent_id = ? AND id = ?", (asset_id, p_id)).fetchone()
                if is_child:
                    raise HTTPException(status_code=400, detail="不能将现有的子设备设为父设备，这会造成循环从属关系")
            fields.append("parent_id = ?")
            params.append(p_id)

        if fields:
            fields.append("updated_at = ?")
            params.append(now)
            params.append(asset_id)
            conn.execute(f"UPDATE assets SET {', '.join(fields)} WHERE id = ?", params)

        # Smart self-learning on update
        if req.name:
            learn_translation(asset_id, req.name.strip(), conn)

    return {"success": True, "message": "资产信息更新成功"}


@router.delete("/{asset_id}")
def delete_asset(asset_id: str, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        # Get all image filenames to delete files from disk
        img_rows = conn.execute("SELECT filename FROM asset_images WHERE asset_id = ?", (asset_id,)).fetchall()
        for r in img_rows:
            fn = r["filename"]
            full_p = UPLOAD_DIR / fn
            thumb_p = THUMB_DIR / fn.replace('.jpg', '_thumb.jpg')
            if full_p.exists():
                try: full_p.unlink()
                except Exception: pass
            if thumb_p.exists():
                try: thumb_p.unlink()
                except Exception: pass

        deleted = conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,)).rowcount
        if deleted == 0:
            raise HTTPException(status_code=404, detail="未找到该资产")

    return {"success": True, "message": "资产及相关图片已彻底删除"}


@router.post("/{asset_id}/images")
async def upload_asset_images(
    asset_id: str,
    files: List[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    with get_db() as conn:
        asset = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="未找到该资产")

    uploaded_results = []
    now = get_now_iso()

    for file in files:
        contents = await file.read()
        if len(contents) == 0:
            continue

        saved_filename, thumb_filename, file_size, mime_type = process_and_save_image(
            contents, file.filename or "photo.jpg"
        )
        img_record_id = uuid.uuid4().hex

        with get_db() as conn:
            # Check if this asset has any primary image
            current_primary = conn.execute(
                "SELECT primary_image_id FROM assets WHERE id = ?", (asset_id,)
            ).fetchone()["primary_image_id"]

            is_primary = 1 if not current_primary else 0

            conn.execute(
                """
                INSERT INTO asset_images (id, asset_id, filename, original_name, file_size, mime_type, is_primary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    img_record_id,
                    asset_id,
                    saved_filename,
                    file.filename,
                    file_size,
                    mime_type,
                    is_primary,
                    now,
                ),
            )

            if is_primary:
                conn.execute(
                    "UPDATE assets SET primary_image_id = ?, updated_at = ? WHERE id = ?",
                    (img_record_id, now, asset_id),
                )
            else:
                conn.execute("UPDATE assets SET updated_at = ? WHERE id = ?", (now, asset_id))

        uploaded_results.append({
            "id": img_record_id,
            "filename": saved_filename,
            "url": f"/uploads/{saved_filename}",
            "thumb_url": f"/uploads/thumbnails/{thumb_filename}",
            "is_primary": bool(is_primary),
        })

    return {"success": True, "uploaded": uploaded_results, "message": f"成功上传 {len(uploaded_results)} 张图片"}


@router.post("/{asset_id}/images/{image_id}/primary")
def set_primary_image(asset_id: str, image_id: str, user: dict = Depends(get_current_user)):
    now = get_now_iso()
    with get_db() as conn:
        img = conn.execute(
            "SELECT id FROM asset_images WHERE id = ? AND asset_id = ?",
            (image_id, asset_id),
        ).fetchone()
        if not img:
            raise HTTPException(status_code=404, detail="图片不存在")

        # Set all to 0, target to 1
        conn.execute("UPDATE asset_images SET is_primary = 0 WHERE asset_id = ?", (asset_id,))
        conn.execute("UPDATE asset_images SET is_primary = 1 WHERE id = ?", (image_id,))
        conn.execute(
            "UPDATE assets SET primary_image_id = ?, updated_at = ? WHERE id = ?",
            (image_id, now, asset_id),
        )

    return {"success": True, "message": "已设为主图"}


@router.delete("/{asset_id}/images/{image_id}")
def delete_image(asset_id: str, image_id: str, user: dict = Depends(get_current_user)):
    now = get_now_iso()
    with get_db() as conn:
        img = conn.execute(
            "SELECT filename, is_primary FROM asset_images WHERE id = ? AND asset_id = ?",
            (image_id, asset_id),
        ).fetchone()
        if not img:
            raise HTTPException(status_code=404, detail="图片不存在")

        filename = img["filename"]
        is_primary = img["is_primary"]

        conn.execute("DELETE FROM asset_images WHERE id = ?", (image_id,))

        # If deleted image was primary, select the next available image
        if is_primary:
            next_img = conn.execute(
                "SELECT id FROM asset_images WHERE asset_id = ? ORDER BY created_at ASC LIMIT 1",
                (asset_id,),
            ).fetchone()
            new_primary_id = next_img["id"] if next_img else None
            if new_primary_id:
                conn.execute("UPDATE asset_images SET is_primary = 1 WHERE id = ?", (new_primary_id,))
            conn.execute(
                "UPDATE assets SET primary_image_id = ?, updated_at = ? WHERE id = ?",
                (new_primary_id, now, asset_id),
            )
        else:
            conn.execute("UPDATE assets SET updated_at = ? WHERE id = ?", (now, asset_id))

        # Delete disk files
        full_p = UPLOAD_DIR / filename
        thumb_p = THUMB_DIR / filename.replace('.jpg', '_thumb.jpg')
        if full_p.exists():
            try: full_p.unlink()
            except Exception: pass
        if thumb_p.exists():
            try: thumb_p.unlink()
            except Exception: pass

    return {"success": True, "message": "图片已删除"}


@router.get("/export/csv")
def export_assets_csv(user: dict = Depends(get_current_user)):
    output = io.StringIO()
    # Write UTF-8 BOM so Microsoft Excel opens it seamlessly without garbled Chinese
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["资产编号(ID)", "资产名称", "所属父设备编号", "所属父设备名称", "存放位置(Location)", "分类", "状态", "备注说明", "创建时间", "更新时间"])

    with get_db() as conn:
        cursor = conn.execute("""
            SELECT a.id, a.name, a.parent_id, p.name AS parent_name, a.location, a.category, a.status, a.description, a.created_at, a.updated_at
            FROM assets a
            LEFT JOIN assets p ON a.parent_id = p.id
            ORDER BY a.id ASC
        """)
        for row in cursor.fetchall():
            writer.writerow([
                row["id"],
                row["name"],
                row["parent_id"] or "",
                row["parent_name"] or "",
                row["location"],
                row["category"],
                row["status"],
                row["description"],
                row["created_at"],
                row["updated_at"],
            ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=assets_export.csv"},
    )

