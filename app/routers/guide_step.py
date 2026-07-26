from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
from urllib.parse import urlparse

from app.database import supabase
from app.config import templates

# Khởi tạo router
router = APIRouter(prefix="/admin", tags=["Guide Steps"])

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
    step_number: int = Form(..., ge=1, description="Số thứ tự phải lớn hơn hoặc bằng 1"),
    title: str = Form(..., min_length=2, max_length=255),
    content: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None)
):
    # Kiểm tra và làm sạch tiêu đề
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Tiêu đề không được để trống hoặc chứa toàn khoảng trắng.")

    # Validate định dạng URL
    validated_image_url = validate_url(image_url, "Đường dẫn Ảnh")
    validated_video_url = validate_url(video_url, "Đường dẫn Video")

    step_data = {
        "guide_id": guide_id,
        "step_number": step_number,
        "title": clean_title,
        "content": content.strip() if content else None,
        "note": note.strip() if note else None,
        "image_url": validated_image_url,
        "video_url": validated_video_url,
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
    is_active: Optional[str] = Form(None)
):
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Tiêu đề không được để trống hoặc chứa toàn khoảng trắng.")

    # Validate định dạng URL khi cập nhật
    validated_image_url = validate_url(image_url, "Đường dẫn Ảnh")
    validated_video_url = validate_url(video_url, "Đường dẫn Video")

    step_data = {
        "step_number": step_number,
        "title": clean_title,
        "content": content.strip() if content else None,
        "note": note.strip() if note else None,
        "image_url": validated_image_url,
        "video_url": validated_video_url,
        "is_active": True if is_active else False
    }

    supabase.table("guide_step").update(step_data).eq("id", step_id).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)


@router.post("/guide-step/{step_id}/delete")
async def delete_guide_step(step_id: int, guide_id: int = Form(...)):
    supabase.table("guide_step").delete().eq("id", step_id).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)