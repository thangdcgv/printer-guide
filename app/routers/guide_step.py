from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
from urllib.parse import urlparse
from app.routers.auth import require_admin
from app.database import supabase
from app.config import templates


# Khởi tạo router kèm theo điều kiện bắt buộc phải đăng nhập
router = APIRouter(
    prefix="/admin", 
    tags=["Guide Steps"],
    dependencies=[Depends(require_admin)] # <--- Khóa toàn bộ các route trong file này
)

# Hàm hỗ trợ kiểm tra tính hợp lệ của URL
def validate_url(url: Optional[str], field_name: str) -> Optional[str]:
    if not url:
        return None
    cleaned_url = url.strip()
    if not cleaned_url:
        return None
    
    parsed = urlparse(cleaned_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=400, 
            detail=f"Trường '{field_name}' không hợp lệ. URL phải bắt đầu bằng http:// hoặc https://"
        )
    return cleaned_url
# Hàm lấy danh sách các bước con dựa vào step_id
def get_sub_steps(step_id: int):
    try:
        response = supabase.table("guide_sub_steps") \
            .select("*") \
            .eq("step_id", step_id) \
            .order("sub_order", desc=False) \
            .execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Lỗi lấy bước con: {e}")
        return []

# --- ROUTE THÊM BƯỚC CON ---
@router.post("/{step_id}/sub-steps/add")
async def add_sub_step(
    step_id: int,
    guide_id: int = Form(...),
    sub_order: int = Form(...),
    content: str = Form(...),
    image_url: str = Form(None),
    note: str = Form(None)
):
    try:
        supabase.table("guide_sub_steps").insert({
            "step_id": step_id,
            "sub_order": sub_order,
            "content": content,
            "image_url": image_url if image_url else None,
            "note": note if note else None
        }).execute()
        
        # Quay lại trang quản lý bước của hướng dẫn hiện tại
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể thêm bước con: {str(e)}")
# --- ROUTE THÊM BƯỚC CON ---
@router.post("/{step_id}/sub-steps/add")
async def add_sub_step(
    step_id: int,
    guide_id: int = Form(...),
    sub_order: int = Form(...),
    content: str = Form(...),
    image_url: str = Form(None),
    note: str = Form(None)
):
    try:
        supabase.table("guide_sub_steps").insert({
            "step_id": step_id,
            "sub_order": sub_order,
            "content": content,
            "image_url": image_url if image_url else None,
            "note": note if note else None
        }).execute()
        
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể thêm bước con: {str(e)}")

# --- ROUTE CẬP NHẬT BƯỚC CON (Mới thêm) ---
@router.post("/sub-steps/{sub_step_id}/update")
async def update_sub_step(
    sub_step_id: int,
    guide_id: int = Form(...),
    sub_order: int = Form(...),
    content: str = Form(...),
    note: str = Form(None)
):
    try:
        supabase.table("guide_sub_steps").update({
            "sub_order": sub_order,
            "content": content,
            "note": note if note else None
        }).eq("id", sub_step_id).execute()
        
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể cập nhật bước con: {str(e)}")

# --- ROUTE XÓA BƯỚC CON ---
@router.post("/sub-steps/{sub_step_id}/delete")
async def delete_sub_step(
    sub_step_id: int,
    guide_id: int = Form(...)
):
    try:
        supabase.table("guide_sub_steps").delete().eq("id", sub_step_id).execute()
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể xóa bước con: {str(e)}")
# --- ROUTE XÓA BƯỚC CON ---
@router.post("/sub-steps/{sub_step_id}/delete")
async def delete_sub_step(
    sub_step_id: int,
    guide_id: int = Form(...)
):
    try:
        supabase.table("guide_sub_steps").delete().eq("id", sub_step_id).execute()
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể xóa bước con: {str(e)}")
@router.get("/guide-step", response_class=HTMLResponse)
async def list_guide_steps(request: Request, guide_id: Optional[int] = None):
    # Nếu truy cập mà không truyền guide_id, chuyển hướng về trang danh sách bài viết
    if not guide_id:
        return RedirectResponse(url="/admin/guide", status_code=303)

    # 1. Lấy thông tin bài hướng dẫn chính
    guide_res = supabase.table("guide").select("*").eq("id", guide_id).execute()
    if not guide_res.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hướng dẫn")
    guide = guide_res.data[0]

    # 2. Lấy danh sách các bước thuộc bài hướng dẫn này
    steps_res = (
        supabase.table("guide_step")
        .select("*")
        .eq("guide_id", guide_id)
        .order("step_number")
        .execute()
    )
    for step in steps_res.data:
        step["sub_steps"] = get_sub_steps(step["id"])
    steps = steps_res.data or []

    return templates.TemplateResponse(
        "guide_steps.html",
        {
            "request": request,
            "guide": guide,
            "steps": steps
        }
    )

@router.post("/guide-step/add/{guide_id}")
async def add_guide_step(
    guide_id: int,
    step_number: int = Form(..., ge=1),
    title: str = Form(..., min_length=2, max_length=255),
    content: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    download_url: Optional[str] = Form(None), # <--- Thêm nhận link tải
    is_active: Optional[str] = Form(None)
):
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Tiêu đề không được để trống.")

    validated_image_url = validate_url(image_url, "Đường dẫn Ảnh")
    validated_video_url = validate_url(video_url, "Đường dẫn Video")
    validated_download_url = validate_url(download_url, "Đường dẫn Tải xuống") # <--- Validate link tải

    step_data = {
        "guide_id": guide_id,
        "step_number": step_number,
        "title": clean_title,
        "content": content.strip() if content else None,
        "note": note.strip() if note else None,
        "image_url": validated_image_url,
        "video_url": validated_video_url,
        "download_url": validated_download_url, # <--- Lưu vào database
        "is_active": True if is_active else False
    }

    supabase.table("guide_step").insert(step_data).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)


# === ROUTE DỰ PHÒNG BẮT TRƯỜNG HỢP URL BỊ THIẾU ID ===
@router.post("/guide-step/add")
async def add_guide_step_fallback(
    guide_id: int = Form(...),
    step_number: int = Form(..., ge=1),
    title: str = Form(..., min_length=2, max_length=255),
    content: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    download_url: Optional[str] = Form(None), # <--- Bổ sung nhận link tải xuống
    is_active: Optional[str] = Form(None)
):
    return await add_guide_step(
        guide_id=guide_id,
        step_number=step_number,
        title=title,
        content=content,
        note=note,
        image_url=image_url,
        video_url=video_url,
        download_url=download_url, # <--- Truyền tiếp xuống hàm chính
        is_active=is_active
    )


@router.post("/guide-step/{step_id}/update/{guide_id}")
async def update_guide_step(
    step_id: int,
    guide_id: int,
    step_number: int = Form(..., ge=1),
    title: str = Form(..., min_length=2, max_length=255),
    content: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    download_url: Optional[str] = Form(None), # <--- Thêm nhận link tải khi sửa
    is_active: Optional[str] = Form(None)
):
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Tiêu đề không được để trống.")

    validated_image_url = validate_url(image_url, "Đường dẫn Ảnh")
    validated_video_url = validate_url(video_url, "Đường dẫn Video")
    validated_download_url = validate_url(download_url, "Đường dẫn Tải xuống")

    step_data = {
        "step_number": step_number,
        "title": clean_title,
        "content": content.strip() if content else None,
        "note": note.strip() if note else None,
        "image_url": validated_image_url,
        "video_url": validated_video_url,
        "download_url": validated_download_url, # <--- Cập nhật vào database
        "is_active": True if is_active else False
    }

    supabase.table("guide_step").update(step_data).eq("id", step_id).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)


@router.post("/guide-step/{step_id}/delete")
async def delete_guide_step(step_id: int, guide_id: int = Form(...)):
    supabase.table("guide_step").delete().eq("id", step_id).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)