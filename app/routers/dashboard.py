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
    Hàm lấy dữ liệu thống kê máy in và chi tiết danh sách bài viết thuộc từng dòng máy.
    """
    try:
        # 1. Lấy danh sách dòng máy in
        models_res = supabase.table("printer_model").select("*").execute()
        printer_models = models_res.data or []

        # 2. Lấy danh sách bài hướng dẫn
        guides_res = (
            supabase.table("guide")
            .select("*")
            .order("is_pinned", desc=True)
            .order("id", desc=True)
            .execute()
        )
        guides = guides_res.data or []

        # --- DEBUG LOG ---
        logger.info(f"==> [DEBUG] Số lượng printer_model lấy được: {len(printer_models)}")
        logger.info(f"==> [DEBUG] Số lượng guide lấy được: {len(guides)}")

        # 3. Lấy góp ý/phản hồi (ĐÃ SỬA: Đổi tên bảng thành 'feedbacks')
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

        # Khởi tạo Map dùng str() làm Key (Hỗ trợ cả ID dạng Số và UUID)
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

        other_guides = []
        for g in guides:
            raw_m_id = g.get("printer_model_id")
            if raw_m_id is None:
                raw_m_id = g.get("model_id") or g.get("printer_id")

            created_at_val = g.get("created_at")
            created_at_str = str(created_at_val) if created_at_val else ""

            guide_item = {
                "id": g.get("id"),
                "title": g.get("title", ""),
                "is_active": g.get("is_active", True),
                "is_pinned": g.get("is_pinned", False),
                "created_at": created_at_str,
            }

            if raw_m_id is not None and str(raw_m_id) in model_map:
                target_key = str(raw_m_id)
                model_map[target_key]["count"] += 1
                model_map[target_key]["guides"].append(guide_item)
            else:
                other_guides.append(guide_item)

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

        return total_guides, total_models, category_stats, unread_feedbacks_count, recent_feedbacks

    except Exception as e:
        logger.error("Lỗi lấy dữ liệu dashboard: %s", e, exc_info=True)
        return 0, 0, [], 0, []


# =========================================================
# 1. PUBLIC DASHBOARD
# =========================================================

@router.get("/dashboard", response_class=HTMLResponse)
def public_dashboard(request: Request):
    """Trang thống kê công khai (dùng def để tránh block event loop)."""
    total_guides, total_models, category_stats, unread_count, feedbacks = fetch_dashboard_stats()

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "total_guides": total_guides,
            "total_models": total_models,
            "category_stats": category_stats,
            "unread_feedbacks_count": unread_count,
            "recent_feedbacks": feedbacks,
            "admin": None,
        },
    )


# =========================================================
# 2. ADMIN DASHBOARD
# =========================================================

@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    admin: dict = Depends(require_login),
):
    """Trang Dashboard quản trị (dùng def để tránh block event loop)."""
    total_guides, total_models, category_stats, unread_count, feedbacks = fetch_dashboard_stats()

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "admin": admin,
            "total_guides": total_guides,
            "total_models": total_models,
            "category_stats": category_stats,
            "unread_feedbacks_count": unread_count,
            "recent_feedbacks": feedbacks,
        },
    )


# =========================================================
# 3. API ĐÁNH DẤU ĐÃ XỬ LÝ / ĐÃ ĐỌC (ADMIN ONLY)
# =========================================================

@router.post("/admin/api/feedback/process/{feedback_id}")
def mark_feedback_processed(
    feedback_id: int,
    admin: dict = Depends(require_login),
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

        logger.info("Admin %s đã xử lý phản hồi ID: %s", admin.get("email", "unknown"), feedback_id)
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