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
    dependencies=[Depends(require_admin)] # Khóa toàn bộ các route trong file này
)

# Hàm hỗ trợ kiểm tra tính hợp lệ của từng URL trong danh sách
def validate_url_list(urls_raw: Optional[str]) -> list[str]:
    if not urls_raw:
        return []
    
    cleaned_urls = []
    for line in urls_raw.splitlines():
        url = line.strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(
                status_code=400, 
                detail=f"Đường dẫn ảnh không hợp lệ: '{url}'. URL phải bắt đầu bằng http:// hoặc https://"
            )
        cleaned_urls.append(url)
    return cleaned_urls

# Hàm hỗ trợ kiểm tra tính hợp lệ của URL đơn (cho Video, Download...)
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
        
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể thêm bước con: {str(e)}")

# --- ROUTE CẬP NHẬT BƯỚC CON ---
@router.post("/{step_id}/sub-steps/add")
async def add_sub_step(
    step_id: int,
    guide_id: int = Form(...),
    sub_order: int = Form(...),
    content: str = Form(...),
    note: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None) # Thêm nhận link ảnh
):
    clean_content = content.strip()
    if not clean_content:
        raise HTTPException(status_code=400, detail="Nội dung ý nhỏ không được để trống.")

    # Validate URL ảnh nếu có nhập
    validated_image_url = validate_url(image_url, "Đường dẫn ảnh ý nhỏ")

    sub_data = {
        "step_id": step_id,
        "sub_order": sub_order,
        "content": clean_content,
        "note": note.strip() if note else None,
        "image_url": validated_image_url
    }

    supabase.table("guide_sub_step").insert(sub_data).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)


@router.post("/sub-steps/{sub_id}/update")
async def update_sub_step(
    sub_id: int,
    guide_id: int = Form(...),
    sub_order: int = Form(...),
    content: str = Form(...),
    note: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None) # Thêm nhận link ảnh
):
    clean_content = content.strip()
    if not clean_content:
        raise HTTPException(status_code=400, detail="Nội dung ý nhỏ không được để trống.")

    validated_image_url = validate_url(image_url, "Đường dẫn ảnh ý nhỏ")

    sub_data = {
        "sub_order": sub_order,
        "content": clean_content,
        "note": note.strip() if note else None,
        "image_url": validated_image_url
    }

    supabase.table("guide_sub_step").update(sub_data).eq("id", sub_id).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)

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
    request: Request, # Thêm request để lấy danh sách form nhiều giá trị
    guide_id: int,
    step_number: int = Form(..., ge=1),
    title: str = Form(..., min_length=2, max_length=255),
    content: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    download_url: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None)
):
    form_data = await request.form()
    image_urls = form_data.getlist("image_url") # Lấy tất cả các ô nhập link ảnh
    
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Tiêu đề không được để trống.")

    # Validate từng URL trong danh sách nhận được từ form
    validated_image_urls = []
    for url in image_urls:
        cleaned = url.strip()
        if not cleaned:
            continue
        parsed = urlparse(cleaned)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(
                status_code=400, 
                detail=f"Đường dẫn ảnh không hợp lệ: '{cleaned}'. URL phải bắt đầu bằng http:// hoặc https://"
            )
        validated_image_urls.append(cleaned)

    validated_video_url = validate_url(video_url, "Đường dẫn Video")
    validated_download_url = validate_url(download_url, "Đường dẫn Tải xuống")

    step_data = {
        "guide_id": guide_id,
        "step_number": step_number,
        "title": clean_title,
        "content": content.strip() if content else None,
        "note": note.strip() if note else None,
        "image_urls": validated_image_urls, # Lưu mảng lên Supabase (kiểu jsonb/array)
        "video_url": validated_video_url,
        "download_url": validated_download_url,
        "is_active": True if is_active else False
    }

    supabase.table("guide_step").insert(step_data).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)


# === ROUTE DỰ PHÒNG BẮT TRƯỜNG HỢP URL BỊ THIẾU ID ===
@router.post("/guide-step/add")
async def add_guide_step_fallback(
    request: Request,
    guide_id: int = Form(...),
    step_number: int = Form(..., ge=1),
    title: str = Form(..., min_length=2, max_length=255),
    content: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    download_url: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None)
):
    return await add_guide_step(
        request=request,
        guide_id=guide_id,
        step_number=step_number,
        title=title,
        content=content,
        note=note,
        video_url=video_url,
        download_url=download_url,
        is_active=is_active
    )


@router.post("/guide-step/{step_id}/update/{guide_id}")
async def update_guide_step(
    request: Request,
    step_id: int,
    guide_id: int,
    step_number: int = Form(..., ge=1),
    title: str = Form(..., min_length=2, max_length=255),
    content: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    download_url: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None)
):
    form_data = await request.form()
    image_urls = form_data.getlist("image_url")

    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Tiêu đề không được để trống.")

    validated_image_urls = []
    for url in image_urls:
        cleaned = url.strip()
        if not cleaned:
            continue
        parsed = urlparse(cleaned)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(
                status_code=400, 
                detail=f"Đường dẫn ảnh không hợp lệ: '{cleaned}'. URL phải bắt đầu bằng http:// hoặc https://"
            )
        validated_image_urls.append(cleaned)

    validated_video_url = validate_url(video_url, "Đường dẫn Video")
    validated_download_url = validate_url(download_url, "Đường dẫn Tải xuống")

    step_data = {
        "step_number": step_number,
        "title": clean_title,
        "content": content.strip() if content else None,
        "note": note.strip() if note else None,
        "image_urls": validated_image_urls,
        "video_url": validated_video_url,
        "download_url": validated_download_url,
        "is_active": True if is_active else False
    }

    supabase.table("guide_step").update(step_data).eq("id", step_id).execute()
    return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=303)