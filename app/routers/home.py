import logging
import re
import unicodedata
from typing import Any, Dict, List, Tuple, Optional
from pydantic import BaseModel

from fastapi import APIRouter, Request, HTTPException, Query
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


def remove_accents(text: str) -> str:
    """Hàm loại bỏ dấu tiếng Việt."""
    if not text:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])


def normalize_text(text: str) -> str:
    """Chuẩn hóa chuỗi: chữ thường, không dấu, bỏ khoảng trắng và ký tự đặc biệt."""
    if not text:
        return ""
    text = remove_accents(text.lower())
    return re.sub(r'[^a-z0-9]', '', text)


def calculate_match_score(guide: Dict[str, Any], norm_kw: str, tokens: List[str]) -> Tuple[bool, int]:
    """Hàm đối chiếu & tính điểm độ liên quan (Relevance Score)."""
    if not norm_kw or not tokens:
        return False, 0

    title = guide.get("title", "")
    desc = guide.get("description", "") or ""
    p_model = guide.get("printer_model") or {}
    brand = p_model.get("brand", "") or ""
    model = p_model.get("model", "") or ""

    norm_title = normalize_text(title)
    norm_desc = normalize_text(desc)
    norm_model = normalize_text(model)
    norm_brand = normalize_text(brand)
    
    corpus = f"{norm_title} {norm_desc} {norm_brand} {norm_model}"
    score = 0

    # 1. BẮT BỘC LỌC MÃ MÁY
    code_tokens = [t for t in tokens if any(c.isdigit() for c in t) and len(t) >= 3]
    if code_tokens:
        has_code_match = any(ct in norm_model or ct in norm_title for ct in code_tokens)
        if not has_code_match:
            return False, 0

    # 2. TÍNH ĐIỂM ĐỘ TƯƠNG QUAN
    if norm_kw in norm_title or norm_kw in norm_model:
        score += 300
    elif norm_kw in corpus:
        score += 100

    match_count = 0
    for t in tokens:
        if t in norm_model:
            score += 80
            match_count += 1
        elif t in norm_title:
            score += 40
            match_count += 1
        elif t in norm_desc:
            score += 10
            match_count += 1

    is_matched = (len(code_tokens) > 0) or (match_count >= len(tokens) * 0.5)
    return is_matched, score


# =====================================================
# 1. TRANG CHỦ PUBLIC
# =====================================================

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    """
    Dùng 'def' để FastAPI tự đẩy I/O Supabase sang ThreadPool.
    Có trả về 'is_db_error' để giao diện hiển thị fallback khi lỗi DB.
    """
    pinned_guides = []
    recent_guides = []
    is_db_error = False
    
    try:
        if supabase:
            # 1. Lấy danh sách bài GHIM
            pinned_res = (
                supabase.table("guide")
                .select("*, printer_model(brand, model)")
                .eq("is_active", True)
                .eq("is_pinned", True)
                .order("id", desc=True)
                .execute()
            )
            pinned_guides = pinned_res.data or []

            # 2. Lấy danh sách bài MỚI (chưa ghim)
            recent_res = (
                supabase.table("guide")
                .select("*, printer_model(brand, model)")
                .eq("is_active", True)
                .eq("is_pinned", False)
                .order("id", desc=True)
                .limit(3)
                .execute()
            )
            recent_guides = recent_res.data or []
        else:
            is_db_error = True

    except Exception as e:
        logger.error(f"❌ Lỗi load trang chủ: {e}")
        is_db_error = True

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Trang chủ",
            "pinned_guides": pinned_guides,
            "recent_guides": recent_guides,
            "is_db_error": is_db_error
        }
    )


# =====================================================
# 2. API & SEARCH ROUTES
# =====================================================

@router.get("/api/search-suggestions")
def search_suggestions(q: str = Query(..., min_length=1)):
    """API trả về JSON phục vụ gợi ý tức thì (Autocomplete)."""
    try:
        keyword = q.strip()
        norm_kw = normalize_text(keyword)
        if not norm_kw:
            return []

        tokens = [t for t in [normalize_text(t) for t in keyword.lower().split()] if t]

        guides_res = (
            supabase.table("guide")
            .select("id, title, description, image_url, printer_model_id, printer_model(brand, model)")
            .eq("is_active", True)
            .execute()
        )
        all_guides = guides_res.data or []

        suggestions_with_score = []
        for g in all_guides:
            is_matched, score = calculate_match_score(g, norm_kw, tokens)
            if is_matched:
                suggestions_with_score.append((score, g))

        suggestions_with_score.sort(key=lambda x: x[0], reverse=True)
        return [g for _, g in suggestions_with_score[:5]]

    except Exception as e:
        logger.error(f"❌ Lỗi API gợi ý tìm kiếm: {e}")
        return []


@router.get("/search", response_class=HTMLResponse)
def search_guides(request: Request, q: str = ""):
    """Trang danh sách kết quả tìm kiếm đầy đủ."""
    keyword = q.strip()
    search_results = []
    is_db_error = False

    try:
        if keyword:
            norm_kw = normalize_text(keyword)
            tokens = [t for t in [normalize_text(t) for t in keyword.lower().split()] if t]

            all_guides_res = (
                supabase.table("guide")
                .select("id, title, description, image_url, video_url, is_active, is_pinned, sort_order, printer_model_id, printer_model(brand, model)")
                .eq("is_active", True)
                .execute()
            )
            all_guides = all_guides_res.data or []

            matched_guides = []
            for g in all_guides:
                is_matched, score = calculate_match_score(g, norm_kw, tokens)
                if is_matched:
                    g_item = dict(g)
                    g_item["_score"] = score
                    matched_guides.append(g_item)

            matched_guides.sort(
                key=lambda x: (
                    not x.get("is_pinned", False),
                    -x.get("_score", 0),
                    x.get("sort_order") or 1
                )
            )

            for g in matched_guides:
                g.pop("_score", None)

            search_results = matched_guides

    except Exception as e:
        logger.error(f"❌ Lỗi tìm kiếm với từ khóa '{keyword}': {e}")
        is_db_error = True

    return templates.TemplateResponse(
        "search_results.html",
        {
            "request": request,
            "keyword": keyword,
            "guides": search_results,
            "is_db_error": is_db_error
        }
    )


# =====================================================
# 3. CHI TIẾT BÀI VIẾT
# =====================================================

@router.get("/guide/{guide_id}", response_class=HTMLResponse)
def view_guide_detail(request: Request, guide_id: int):
    # 1. Lấy thông tin bài viết + printer_model + tác giả trong 1 query duy nhất (Tối ưu performance)
    try:
        guide_res = (
            supabase.table("guide")
            .select("*, printer_model(brand, model), quan_tri_vien(ho_ten, username)")
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
        logger.error(f"❌ Lỗi khi load chi tiết bài guide #{guide_id}: {e}")
        raise HTTPException(status_code=500, detail="Lỗi máy chủ khi tải nội dung bài viết")

    # 2. Lấy các bước hướng dẫn (Steps & Sub-steps)
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
        logger.error(f"❌ Lỗi lấy các bước của bài guide #{guide_id}: {e}")
        steps = []

    printer_model_id = guide.get("printer_model_id")

    # 3. LẤY BÀI VIẾT TIẾP THEO
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

    # 4. LẤY BÀI VIẾT LIÊN QUAN
    related_guides = []

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


# =====================================================
# 4. FEEDBACK API
# =====================================================

class FeedbackPayload(BaseModel):
    category: str
    rating: int
    content: str
    page_url: Optional[str] = None

@router.post("/api/feedback")
def create_feedback(data: FeedbackPayload):
    try:
        feedback_data = {
            "category": data.category,
            "rating": data.rating,
            "content": data.content,
            "page_url": data.page_url
        }
        supabase.table("feedbacks").insert(feedback_data).execute()
        return {"success": True, "message": "Gửi phản hồi thành công"}
    except Exception as e:
        logger.error(f"❌ Lỗi lưu feedback: {e}")
        raise HTTPException(status_code=500, detail="Không thể lưu phản hồi")