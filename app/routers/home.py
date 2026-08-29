import logging
import re
import unicodedata
from typing import Any, Dict, List, Tuple
from typing import Optional
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


# =====================================================
# 1. TRANG CHỦ
# =====================================================

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    pinned_guides = []
    recent_guides = []
    
    try:
        # 1. Lấy danh sách các bài viết được GHIM (is_pinned = True)
        pinned_res = (
            supabase.table("guide")
            .select("*")
            .eq("is_active", True)
            .eq("is_pinned", True)
            .order("id", desc=True)
            .execute()
        )
        pinned_guides = pinned_res.data or []

        # 2. Lấy các bài viết mới cập nhật chưa ghim (để tránh trùng lặp)
        recent_res = (
            supabase.table("guide")
            .select("*")
            .eq("is_active", True)
            .eq("is_pinned", False)
            .order("id", desc=True)
            .limit(3)
            .execute()
        )
        recent_guides = recent_res.data or []

    except Exception as e:
        logger.error(f"Lỗi load trang chủ: {e}")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Trang chủ",
            "pinned_guides": pinned_guides,
            "recent_guides": recent_guides
        }
    )
# =====================================================
# 1. HELPER FUNCTIONS & LOGIC TÌM KIẾM CHUNG
# =====================================================

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
    """
    Hàm đối chiếu & tính điểm độ liên quan (Relevance Score).
    Trả về: (is_matched: bool, score: int)
    """
    # Guard clause: Tránh lỗi khi chuỗi tìm kiếm rỗng
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

    # 1. BẮT BỘC LỌC MÃ MÁY (Nếu câu truy vấn chứa mã máy có số như l8050, c5290, pro1000)
    code_tokens = [t for t in tokens if any(c.isdigit() for c in t) and len(t) >= 3]
    
    if code_tokens:
        # Bắt buộc bài viết phải chứa ít nhất 1 mã máy mà người dùng đã gõ
        has_code_match = any(ct in norm_model or ct in norm_title for ct in code_tokens)
        if not has_code_match:
            return False, 0  # Loại ngay bài viết của máy khác (như C5290)

    # 2. TÍNH ĐIỂM ĐỘ TƯƠNG QUAN
    # Ưu tiên cao nhất: Khớp nguyên cụm từ tìm kiếm trong tiêu đề hoặc tên model
    if norm_kw in norm_title or norm_kw in norm_model:
        score += 300
    elif norm_kw in corpus:
        score += 100

    # Cộng điểm chi tiết theo vị trí xuất hiện của từng từ (Token)
    match_count = 0
    for t in tokens:
        if t in norm_model:
            score += 80   # Khớp đúng mã/thương hiệu máy
            match_count += 1
        elif t in norm_title:
            score += 40   # Khớp trong tiêu đề bài viết
            match_count += 1
        elif t in norm_desc:
            score += 10   # Khớp trong mô tả
            match_count += 1

    # Điều kiện chấp nhận: Có khớp mã máy HOẶC tỷ lệ từ khóa khớp >= 50%
    is_matched = (len(code_tokens) > 0) or (match_count >= len(tokens) * 0.5)

    return is_matched, score


# =====================================================
# 2. API ROUTES
# =====================================================

@router.get("/api/search-suggestions")
async def search_suggestions(q: str = Query(..., min_length=1)):
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

        # Ưu tiên các gợi ý có điểm độ tương quan cao nhất
        suggestions_with_score.sort(key=lambda x: x[0], reverse=True)
        return [g for _, g in suggestions_with_score[:5]]

    except Exception as e:
        logger.error(f"Lỗi API gợi ý tìm kiếm: {e}")
        return []


@router.get("/search", response_class=HTMLResponse)
async def search_guides(request: Request, q: str = ""):
    """Trang danh sách kết quả tìm kiếm đầy đủ."""
    keyword = q.strip()
    search_results = []

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

            # Sắp xếp ưu tiên: (1) Đã ghim -> (2) Điểm khớp cao -> (3) Thứ tự sort_order
            matched_guides.sort(
                key=lambda x: (
                    not x.get("is_pinned", False),
                    -x.get("_score", 0),
                    x.get("sort_order") or 1
                )
            )

            # Làm sạch dữ liệu tạm trước khi gửi sang Template
            for g in matched_guides:
                g.pop("_score", None)

            search_results = matched_guides

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

        # 🆕 BỔ SUNG: Lấy thông tin tác giả bài viết từ created_by
        created_by_id = guide.get("created_by")
        if created_by_id:
            try:
                author_res = (
                    supabase.table("quan_tri_vien")
                    .select("ho_ten, username")
                    .eq("id", created_by_id)
                    .execute()
                )
                guide["quan_tri_vien"] = author_res.data[0] if author_res.data else None
            except Exception as e:
                logger.warning(f"Lỗi lấy thông tin tác giả cho guide #{guide_id}: {e}")
                guide["quan_tri_vien"] = None
        else:
            guide["quan_tri_vien"] = None

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

class FeedbackPayload(BaseModel):
    category: str
    rating: int
    content: str
    page_url: Optional[str] = None

@router.post("/api/feedback")
async def create_feedback(data: FeedbackPayload):
    try:
        feedback_data = {
            "category": data.category,
            "rating": data.rating,
            "content": data.content,
            "page_url": data.page_url
        }
        
        # Lưu vào bảng "feedbacks" trong Supabase
        supabase.table("feedbacks").insert(feedback_data).execute()
        return {"success": True, "message": "Gửi phản hồi thành công"}
    except Exception as e:
        logger.error(f"Lỗi lưu feedback: {e}")
        raise HTTPException(status_code=500, detail="Không thể lưu phản hồi")