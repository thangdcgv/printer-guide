import logging
import re
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import supabase  

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Public Home & Guide"])
templates = Jinja2Templates(directory="app/templates")

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def auto_linkify(text: Optional[str]) -> str:
    """Tự động chuyển các chuỗi URL (http/https) thành thẻ <a> có thể bấm được."""
    if not text:
        return ""
    url_pattern = re.compile(r'(https?://[^\s<>]+)')
    def replace_url(match):
        url = match.group(0)
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer" style="color: #2563eb; text-decoration: underline; font-weight: 500;" title="{url}">🔗 {url}</a>'
    return url_pattern.sub(replace_url, text)


# =====================================================
# 1. TRANG CHỦ
# =====================================================

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        res = (
            supabase.table("guide")
            .select("*")
            .eq("is_active", True)
            .order("id", desc=True)
            .limit(3)
            .execute()
        )
        recent_guides = res.data or []
    except Exception as e:
        logger.error(f"Lỗi load trang chủ: {e}")
        recent_guides = []

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Trang chủ",
            "recent_guides": recent_guides
        }
    )


# =====================================================
# 2. TRANG TÌM KIẾM
# =====================================================

@router.get("/search", response_class=HTMLResponse)
async def search_guides(request: Request, q: str = ""):
    keyword = q.strip()
    search_results = []
    
    try:
        if keyword:
            title_res = (
                supabase.table("guide")
                .select("*")
                .eq("is_active", True)
                .ilike("title", f"%{keyword}%")
                .execute()
            )
            title_matches = title_res.data or []
            
            model_res = (
                supabase.table("printer_model")
                .select("id")
                .or_(f"brand.ilike.%{keyword}%,model.ilike.%{keyword}%")
                .execute()
            )
            matched_model_ids = [m["id"] for m in (model_res.data or [])]
            
            model_matches = []
            if matched_model_ids:
                guide_res = (
                    supabase.table("guide")
                    .select("*")
                    .eq("is_active", True)
                    .in_("printer_model_id", matched_model_ids)
                    .execute()
                )
                model_matches = guide_res.data or []
            
            combined_dict = {guide["id"]: guide for guide in title_matches + model_matches}
            search_results = list(combined_dict.values())

    except Exception as e:
        logger.error(f"Lỗi tìm kiếm với từ khóa '{keyword}': {e}")
        search_results = []

    return templates.TemplateResponse(
        "search_results.html",
        {
            "request": request,
            "keyword": keyword,
            "guides": search_results
        }
    )


# =====================================================
# 3. TRANG CHI TIẾT BÀI VIẾT & BÀI LIÊN QUAN
# =====================================================

@router.get("/guide/{guide_id}", response_class=HTMLResponse)
async def view_guide_detail(request: Request, guide_id: int):
    # 1. Lấy thông tin bài hướng dẫn chính
    try:
        guide_res = (
            supabase.table("guide")
            .select("*, printer_model(brand, model)")
            .eq("id", guide_id)
            .eq("is_active", True) 
            .execute()
        )
        if not guide_res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy bài hướng dẫn hoặc bài viết đã bị ẩn")
        guide = guide_res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi load chi tiết bài guide #{guide_id}: {e}")
        raise HTTPException(status_code=500, detail="Lỗi máy chủ khi tải nội dung bài viết")

    # 2. Lấy danh sách các bước lớn & bước con
    try:
        steps_res = (
            supabase.table("guide_step")
            .select("*")
            .eq("guide_id", guide_id)
            .eq("is_active", True)
            .order("step_number")
            .execute()
        )
        steps = steps_res.data or []

        if steps:
            step_ids = [step["id"] for step in steps]
            sub_res = (
                supabase.table("guide_sub_steps")
                .select("*")
                .in_("step_id", step_ids)
                .order("sub_order")
                .execute()
            )
            all_sub_steps = sub_res.data or []

            sub_map = {sid: [] for sid in step_ids}
            for sub in all_sub_steps:
                sub_map[sub["step_id"]].append(sub)
            
            for step in steps:
                step["sub_steps"] = sub_map.get(step["id"], [])
                step["content"] = auto_linkify(step.get("content"))
                step["note"] = auto_linkify(step.get("note"))
                for sub in step["sub_steps"]:
                    sub["content"] = auto_linkify(sub.get("content"))
                    sub["note"] = auto_linkify(sub.get("note"))
    except Exception as e:
        logger.error(f"Lỗi lấy các bước của bài guide #{guide_id}: {e}")
        steps = []

    printer_model_id = guide.get("printer_model_id")

    # 3. LẤY BÀI VIẾT TIẾP THEO (NEXT GUIDE)
    next_guide = None
    if printer_model_id:
        try:
            current_sort = guide.get("sort_order") or 0
            next_res = (
                supabase.table("guide")
                .select("id, title, sort_order")
                .eq("printer_model_id", printer_model_id)
                .gt("sort_order", current_sort)
                .neq("id", guide_id)
                .eq("is_active", True)
                .order("sort_order", desc=False)
                .limit(1)
                .execute()
            )
            if next_res.data:
                next_guide = next_res.data[0]
        except Exception as e:
            logger.warning(f"Lỗi lấy next_guide: {e}")

    # 4. LẤY BÀI VIẾT LIÊN QUAN (TÁCH BIỆT 3 CẤP XỬ LÝ)
    related_guides = []

    # CẤP 1: Lấy bài cùng dòng máy (printer_model_id)
    if printer_model_id:
        try:
            res1 = (
                supabase.table("guide")
                .select("id, title, image_url, video_url, sort_order")
                .eq("printer_model_id", printer_model_id)
                .neq("id", guide_id)
                .eq("is_active", True)
                .order("sort_order", desc=False)
                .limit(3)
                .execute()
            )
            related_guides = res1.data or []
        except Exception as e:
            logger.warning(f"[Gợi ý Cấp 1] Lỗi query printer_model_id: {e}")

    # CẤP 2: Lấy bài cùng từ khóa trong tiêu đề (ví dụ: L1300)
    if not related_guides and guide.get("title"):
        try:
            title = guide["title"]
            words = re.findall(r'\b[A-Za-z0-9\-]+\b', title)
            model_keywords = [w for w in words if any(c.isdigit() for c in w)]
            search_kw = model_keywords[0] if model_keywords else (words[0] if words else None)

            if search_kw:
                res2 = (
                    supabase.table("guide")
                    .select("id, title, image_url, video_url")
                    .ilike("title", f"%{search_kw}%")
                    .neq("id", guide_id)
                    .eq("is_active", True)
                    .order("id", desc=True)
                    .limit(3)
                    .execute()
                )
                related_guides = res2.data or []
        except Exception as e:
            logger.warning(f"[Gợi ý Cấp 2] Lỗi query theo từ khóa: {e}")

    # CẤP 3: Lấy 3 bài mới nhất toàn hệ thống (Fallback)
    if not related_guides:
        try:
            res3 = (
                supabase.table("guide")
                .select("id, title, image_url, video_url")
                .neq("id", guide_id)
                .eq("is_active", True)
                .order("id", desc=True)
                .limit(3)
                .execute()
            )
            related_guides = res3.data or []
        except Exception as e:
            logger.error(f"[Gợi ý Cấp 3] Lỗi lấy bài mới nhất: {e}")

    return templates.TemplateResponse(
        "guide_detail.html",
        {
            "request": request,
            "guide": guide,
            "steps": steps,
            "next_guide": next_guide,
            "related_guides": related_guides
        }
    )