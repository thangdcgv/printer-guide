import logging
from typing import Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse

from app.config import templates
from app.database import supabase
from app.routers.auth import require_login

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Dashboard"])


# =========================================================
# SCHEMAS (PYDANTIC MODEL)
# =========================================================

class FeedbackCreateSchema(BaseModel):
    category: str = Field(..., max_length=50, description="Phân loại: bug | ui | other")
    rating: int = Field(..., ge=1, le=5, description="Đánh giá từ 1 đến 5 sao")
    content: str = Field(..., min_length=1, description="Nội dung phản hồi")
    page_url: Optional[str] = Field(None, description="Đường dẫn URL trang người dùng gửi góp ý")


# =========================================================
# HELPER: LẤY DỮ LIỆU THỐNG KÊ
# =========================================================
def fetch_dashboard_stats():
    """
    Hàm lấy dữ liệu thống kê máy in, chi tiết bài viết và thống kê theo tác giả.
    """
    try:
        # 1. Lấy danh sách dòng máy in
        models_res = supabase.table("printer_model").select("*").execute()
        printer_models = models_res.data or []

        # 2. Lấy danh sách bài hướng dẫn + JOIN bảng quan_tri_vien
        guides_res = (
            supabase.table("guide")
            .select("*, quan_tri_vien(ho_ten, username)")
            .order("is_pinned", desc=True)
            .order("id", desc=True)
            .execute()
        )
        guides = guides_res.data or []

        # 3. Lấy góp ý/phản hồi
        unread_feedbacks_count = 0
        recent_feedbacks = []
        try:
            fb_res = (
                supabase.table("feedbacks")
                .select("*")
                .order("created_at", desc=True)
                .limit(10)
                .execute()
            )
            recent_feedbacks = fb_res.data or []

            unread_res = (
                supabase.table("feedbacks")
                .select("id", count="exact")
                .eq("is_processed", False)
                .execute()
            )
            unread_feedbacks_count = unread_res.count if unread_res.count is not None else 0
        except Exception as fb_err:
            logger.warning("Không thể lấy dữ liệu feedback: %s", fb_err)

        total_guides = len(guides)
        total_models = len(printer_models)

        # Map thống kê theo model
        model_map = {}
        for m in printer_models:
            m_id = m.get("id")
            if m_id is not None:
                key_id = str(m_id)
                brand = m.get("brand", "") or ""
                model = m.get("model", "") or ""
                model_map[key_id] = {
                    "printer_model_id": key_id,
                    "brand": brand,
                    "model": model,
                    "display_name": f"{brand} {model}".strip() or f"Model #{key_id}",
                    "count": 0,
                    "guides": [],
                }

        # Khởi tạo Map gom nhóm bài viết theo Tác giả
        author_map = {}

        other_guides = []
        for g in guides:
            raw_m_id = g.get("printer_model_id")
            created_at_val = g.get("created_at")
            created_at_str = str(created_at_val) if created_at_val else ""

            # Lấy thông tin tác giả từ cột ho_ten hoặc username từ relation quan_tri_vien
            qtv_info = g.get("quan_tri_vien")
            author_name = "Chưa rõ"

            if isinstance(qtv_info, dict):
                author_name = qtv_info.get("ho_ten") or qtv_info.get("username") or author_name
            elif isinstance(qtv_info, list) and len(qtv_info) > 0:
                author_name = qtv_info[0].get("ho_ten") or qtv_info[0].get("username") or author_name
            elif g.get("created_by"):
                author_name = f"QTV #{g.get('created_by')}"

            is_active = g.get("is_active", True)
            is_pinned = g.get("is_pinned", False)

            guide_item = {
                "id": g.get("id"),
                "title": g.get("title", ""),
                "is_active": is_active,
                "is_pinned": is_pinned,
                "created_at": created_at_str,
                "author_name": author_name,
            }

            # Gom nhóm bài viết theo danh mục máy in
            if raw_m_id is not None and str(raw_m_id) in model_map:
                target_key = str(raw_m_id)
                model_map[target_key]["count"] += 1
                model_map[target_key]["guides"].append(guide_item)
            else:
                other_guides.append(guide_item)

            # Tính toán số lượng bài viết cho từng tác giả
            if author_name not in author_map:
                author_map[author_name] = {
                    "author_name": author_name,
                    "total_guides": 0,
                    "pinned_count": 0,
                    "active_count": 0,
                }
            author_map[author_name]["total_guides"] += 1
            if is_pinned:
                author_map[author_name]["pinned_count"] += 1
            if is_active:
                author_map[author_name]["active_count"] += 1

        category_stats = list(model_map.values())

        if other_guides:
            category_stats.append({
                "printer_model_id": "other",
                "brand": "Chung",
                "model": "Khác",
                "display_name": "Tài liệu chung / Khác",
                "count": len(other_guides),
                "guides": other_guides,
            })

        # Sắp xếp danh sách tác giả theo số bài viết giảm dần
        author_stats = sorted(list(author_map.values()), key=lambda x: x["total_guides"], reverse=True)

        return total_guides, total_models, category_stats, unread_feedbacks_count, recent_feedbacks, author_stats

    except Exception as e:
        logger.error("Lỗi lấy dữ liệu dashboard: %s", e, exc_info=True)
        return 0, 0, [], 0, [], []


# =========================================================
# 1. PUBLIC DASHBOARD
# =========================================================

@router.get("/dashboard", response_class=HTMLResponse)
def public_dashboard(request: Request):
    """Trang thống kê công khai (dùng def để tránh block event loop)."""
    (
        total_guides,
        total_models,
        category_stats,
        unread_count,
        feedbacks,
        author_stats,
    ) = fetch_dashboard_stats()

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "total_guides": total_guides,
            "total_models": total_models,
            "category_stats": category_stats,
            "unread_feedbacks_count": unread_count,
            "recent_feedbacks": feedbacks,
            "author_stats": author_stats,
            "admin": None,
        },
    )


# =========================================================
# 2. ADMIN DASHBOARD (ĐÃ SỬA LỖI)
# =========================================================

@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(  # 1. Thêm 'async' để đồng bộ với require_login
    request: Request,
    current_user: dict = Depends(require_login),
):
    """Trang Dashboard quản trị."""
    (
        total_guides,
        total_models,
        category_stats,
        unread_count,
        feedbacks,
        author_stats,
    ) = fetch_dashboard_stats()

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "admin": current_user,  # 2. BỔ SUNG DÒNG NÀY (hoặc "admin": True) để HTML {% if admin %} nhận diện được!
            "total_guides": total_guides,
            "total_models": total_models,
            "category_stats": category_stats,
            "unread_feedbacks_count": unread_count,
            "recent_feedbacks": feedbacks,
            "author_stats": author_stats,
        },
    )


# =========================================================
# 3. API ĐÁNH DẤU ĐÃ XỬ LÝ / ĐÃ ĐỌC (ADMIN ONLY)
# =========================================================

@router.post("/admin/api/feedback/process/{feedback_id}")
def mark_feedback_processed(
    feedback_id: int,
    current_user: dict = Depends(require_login),
):
    """Cập nhật trạng thái phản hồi thành 'Đã xử lý'."""
    try:
        res = (
            supabase.table("feedbacks")
            .update({"is_processed": True})
            .eq("id", feedback_id)
            .execute()
        )

        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy phản hồi với ID: {feedback_id}"
            )

        logger.info("Admin %s đã xử lý phản hồi ID: %s", current_user.get("email", "unknown"), feedback_id)
        return {
            "success": True,
            "message": "Đã đánh dấu xử lý phản hồi thành công.",
            "data": res.data[0]
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Lỗi khi cập nhật trạng thái phản hồi %s: %s", feedback_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi hệ thống khi cập nhật phản hồi: {str(e)}"
        )


# =========================================================
# 4. API TẠO PHẢN HỒI MỚI (PUBLIC USER)
# =========================================================

@router.post("/api/feedback")
def create_user_feedback(payload: FeedbackCreateSchema):
    """Lưu phản hồi mới từ người dùng vào bảng `feedbacks`."""
    try:
        new_feedback = {
            "category": payload.category,
            "rating": payload.rating,
            "content": payload.content.strip(),
            "page_url": payload.page_url,
            "is_processed": False,
        }

        res = supabase.table("feedbacks").insert(new_feedback).execute()

        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể lưu phản hồi vào cơ sở dữ liệu."
            )

        return {
            "success": True,
            "message": "Cảm ơn bạn đã gửi phản hồi!",
            "data": res.data[0]
        }

    except Exception as e:
        logger.error("Lỗi khi tạo phản hồi mới: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể gửi phản hồi lúc này. Vui lòng thử lại sau."
        )