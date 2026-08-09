import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.config import templates
from app.database import supabase
from app.routers.auth import require_login  

logger = logging.getLogger(__name__)

class ReorderRequest(BaseModel):
    ordered_ids: List[int]

router = APIRouter(
    prefix="/admin", 
    tags=["Guide Steps"],
    dependencies=[Depends(require_login)]  # ➔ THAY ĐỔI: Cho phép mọi user đã đăng nhập thao tác
)

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def auto_linkify(text: Optional[str]) -> str:
    """Tự động chuyển các chuỗi link (http/https) thành thẻ <a> có thể nhấp được."""
    if not text:
        return ""
    url_pattern = re.compile(r'(https?://[^\s<>]+)')
    def replace_url(match):
        url = match.group(0)
        return f'<a href="{url}" target="_blank" style="color: #2563eb; text-decoration: underline; font-weight: 500;" title="{url}">🔗 {url}</a>'
    return url_pattern.sub(replace_url, text)


def validate_url(url: Optional[str], field_name: str) -> Optional[str]:
    """Kiểm tra tính hợp lệ của 1 URL đơn."""
    if not url:
        return None
    cleaned_url = url.strip()
    if not cleaned_url:
        return None
    
    parsed = urlparse(cleaned_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Trường '{field_name}' không hợp lệ. URL phải bắt đầu bằng http:// hoặc https://"
        )
    return cleaned_url


def validate_url_list(urls: List[str], field_name: str = "Đường dẫn ảnh") -> List[str]:
    """Kiểm tra tính hợp lệ của một danh sách URL."""
    validated_urls = []
    for url in urls:
        cleaned = url.strip()
        if not cleaned:
            continue
        parsed = urlparse(cleaned)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"{field_name} không hợp lệ: '{cleaned}'. URL phải bắt đầu bằng http:// hoặc https://"
            )
        validated_urls.append(cleaned)
    return validated_urls


def get_sub_steps_batch(step_ids: List[int]) -> dict:
    """
    Tối ưu hóa: Lấy tất cả sub-steps cho danh sách step_ids trong 1 truy vấn duy nhất (Tránh N+1).
    """
    if not step_ids:
        return {}
    try:
        response = (
            supabase.table("guide_sub_steps")
            .select("*")
            .in_("step_id", step_ids)
            .order("sub_order", desc=False)
            .execute()
        )
        sub_steps_map = {sid: [] for sid in step_ids}
        for sub in (response.data or []):
            sub_steps_map[sub["step_id"]].append(sub)
        return sub_steps_map
    except Exception as e:
        logger.error(f"Lỗi lấy danh sách bước con batch: {e}")
        return {}


# =====================================================
# BƯỚC CON (SUB-STEPS)
# =====================================================

@router.post("/{step_id}/sub-steps/add")
async def add_sub_step(
    step_id: int,
    guide_id: int = Form(...),
    sub_order: int = Form(...),
    content: str = Form(...),
    note: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None)
):
    clean_content = content.strip()
    if not clean_content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nội dung ý nhỏ không được để trống.")

    validated_image_url = validate_url(image_url, "Đường dẫn ảnh ý nhỏ")

    sub_data = {
        "step_id": step_id,
        "sub_order": sub_order,
        "content": clean_content,
        "note": note.strip() if note else None,
        "image_url": validated_image_url
    }

    try:
        supabase.table("guide_sub_steps").insert(sub_data).execute()
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Lỗi thêm bước con: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Không thể thêm bước con: {str(e)}")


@router.post("/sub-steps/{sub_id}/update")
async def update_sub_step(
    sub_id: int,
    guide_id: int = Form(...),
    sub_order: int = Form(...),
    content: str = Form(...),
    note: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None)
):
    clean_content = content.strip()
    if not clean_content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nội dung ý nhỏ không được để trống.")

    validated_image_url = validate_url(image_url, "Đường dẫn ảnh ý nhỏ")

    sub_data = {
        "sub_order": sub_order,
        "content": clean_content,
        "note": note.strip() if note else None,
        "image_url": validated_image_url
    }

    try:
        supabase.table("guide_sub_steps").update(sub_data).eq("id", sub_id).execute()
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Lỗi cập nhật bước con #{sub_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Không thể cập nhật bước con: {str(e)}")


@router.post("/sub-steps/{sub_step_id}/delete")
async def delete_sub_step(
    sub_step_id: int,
    guide_id: int = Form(...)
):
    try:
        supabase.table("guide_sub_steps").delete().eq("id", sub_step_id).execute()
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Lỗi xóa bước con: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Không thể xóa bước con: {str(e)}")


# =====================================================
# BƯỚC LỚN (GUIDE STEPS)
# =====================================================

@router.get("/guide-step", response_class=HTMLResponse)
async def list_guide_steps(
    request: Request, 
    guide_id: Optional[int] = None,
    current_user: dict = Depends(require_login)  # ➔ THAY ĐỔI: Dùng require_login
):
    if not guide_id:
        return RedirectResponse(url="/admin/guide", status_code=status.HTTP_303_SEE_OTHER)

    # 1. Lấy thông tin bài hướng dẫn chính
    guide_res = supabase.table("guide").select("*").eq("id", guide_id).execute()
    if not guide_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bài hướng dẫn")
    guide = guide_res.data[0]

    # 2. Lấy danh sách các bước thuộc bài hướng dẫn
    steps_res = (
        supabase.table("guide_step")
        .select("*")
        .eq("guide_id", guide_id)
        .order("step_number")
        .execute()
    )
    
    steps = steps_res.data or []
    
    # 3. Lấy tập trung sub_steps cho toàn bộ các steps trong 1 query duy nhất
    step_ids = [step["id"] for step in steps]
    sub_steps_map = get_sub_steps_batch(step_ids)
    
    for step in steps:
        step["sub_steps"] = sub_steps_map.get(step["id"], [])
        
        # Tự động nhận dạng link cho nội dung và lưu ý
        step["content"] = auto_linkify(step.get("content"))
        step["note"] = auto_linkify(step.get("note"))
        
        for sub in step["sub_steps"]:
            sub["content"] = auto_linkify(sub.get("content"))
            sub["note"] = auto_linkify(sub.get("note"))

    return templates.TemplateResponse(
        "guide_steps.html",
        {
            "request": request,
            "user": current_user,  
            "guide": guide,
            "steps": steps
        }
    )


@router.post("/guide-step/reorder")
async def reorder_guide_steps(payload: ReorderRequest):
    try:
        for index, step_id in enumerate(payload.ordered_ids, start=1):
            supabase.table("guide_step").update({
                "step_number": index
            }).eq("id", step_id).execute()
            
        return {"success": True, "message": "Cập nhật thứ tự thành công"}
    except Exception as e:
        logger.error(f"Lỗi sắp xếp các bước: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Lỗi sắp xếp: {str(e)}")


@router.post("/guide-step/add/{guide_id}")
async def add_guide_step(
    request: Request,
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tiêu đề không được để trống.")

    validated_image_urls = validate_url_list(image_urls, "Đường dẫn ảnh")
    validated_video_url = validate_url(video_url, "Đường dẫn Video")
    validated_download_url = validate_url(download_url, "Đường dẫn Tải xuống")

    try:
        # Tự động đẩy lùi các bước cũ nếu trùng step_number
        existing_steps = (
            supabase.table("guide_step")
            .select("id, step_number")
            .eq("guide_id", guide_id)
            .gte("step_number", step_number)
            .order("step_number", desc=True)
            .execute()
        )

        if existing_steps.data:
            for s in existing_steps.data:
                supabase.table("guide_step").update({
                    "step_number": s["step_number"] + 1
                }).eq("id", s["id"]).execute()

        step_data = {
            "guide_id": guide_id,
            "step_number": step_number,
            "title": clean_title,
            "content": content.strip() if content else None,
            "note": note.strip() if note else None,
            "image_urls": validated_image_urls,
            "video_url": validated_video_url,
            "download_url": validated_download_url,
            "is_active": is_active in ["true", "on", "1"]
        }

        supabase.table("guide_step").insert(step_data).execute()
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Lỗi thêm bước lớn: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Không thể thêm bước lớn: {str(e)}")


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tiêu đề không được để trống.")

    validated_image_urls = validate_url_list(image_urls, "Đường dẫn ảnh")
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
        "is_active": is_active in ["true", "on", "1"]
    }

    try:
        supabase.table("guide_step").update(step_data).eq("id", step_id).execute()
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Lỗi cập nhật bước lớn #{step_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Không thể cập nhật bước lớn: {str(e)}")


@router.post("/guide-step/{step_id}/delete")
async def delete_guide_step(
    step_id: int,
    guide_id: int = Form(...)
):
    try:
        supabase.table("guide_sub_steps").delete().eq("step_id", step_id).execute()
        supabase.table("guide_step").delete().eq("id", step_id).execute()
        return RedirectResponse(url=f"/admin/guide-step?guide_id={guide_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.error(f"Lỗi xóa bước lớn: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Không thể xóa bước lớn: {str(e)}")