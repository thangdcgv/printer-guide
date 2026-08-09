import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import templates
from app.database import supabase
from app.routers.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Hub"])


# =========================================================
# 1. TRANG QUẢN TRỊ TRUNG TÂM (HIỂN THỊ admin.html)
# URL: GET /admin
# =========================================================
@router.get("", response_class=HTMLResponse)
async def admin_main(
    request: Request,
    admin: dict = Depends(require_admin),  # Tự động xác thực & redirect nếu chưa login
):
    """
    Trang Hub chính hiển thị 3 card chức năng và nút Thống kê trên Header
    """
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "admin": admin,  # Truyền dict admin chuẩn vào context
        },
    )


# =========================================================
# 2. TRANG BÁO CÁO THỐNG KÊ & FEEDBACK (HIỂN THỊ admin_dashboard.html)
# URL: GET /admin/dashboard
# =========================================================
@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin: dict = Depends(require_admin),
):
    """
    Trang chi tiết thống kê bài viết, dòng máy in và các phản hồi/góp ý
    """
    try:
        models_res = supabase.table("printer_model").select("*").execute()
        guides_res = supabase.table("guide").select("*").execute()

        unread_fb_res = (
            supabase.table("feedbacks")
            .select("id", count="exact")
            .eq("is_processed", False)
            .execute()
        )
        recent_fb_res = (
            supabase.table("feedbacks")
            .select("*")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )

        guides = guides_res.data or []
        printer_models = models_res.data or []

        model_map = {
            m["id"]: {
                "display_name": f"{m.get('brand', '')} - {m.get('model', '')}".strip(" -")
                or "Chưa đặt tên",
                "count": 0,
            }
            for m in printer_models
        }
        other_guides_count = 0

        for g in guides:
            m_id = g.get("printer_model_id") or g.get("model_id")
            if m_id and m_id in model_map:
                model_map[m_id]["count"] += 1
            else:
                other_guides_count += 1

        category_stats = [
            {"name": v["display_name"], "count": v["count"]}
            for v in model_map.values()
        ]
        if other_guides_count > 0:
            category_stats.append(
                {"name": "Tài liệu chung / Khác", "count": other_guides_count}
            )

        return templates.TemplateResponse(
            "admin_dashboard.html",
            {
                "request": request,
                "admin": admin,
                "total_guides": len(guides),
                "total_models": len(printer_models),
                "category_stats": category_stats,
                "unread_feedbacks_count": unread_fb_res.count or 0,
                "recent_feedbacks": recent_fb_res.data or [],
                "system_logs": [],
                "today_logs_count": 0,
            },
        )
    except Exception as e:
        logger.error("Lỗi khi tải dữ liệu Dashboard Thống kê: %s", e)
        return templates.TemplateResponse(
            "admin_dashboard.html",
            {
                "request": request,
                "admin": admin,
            },
        )


# =========================================================
# 3. API ĐÁNH DẤU XỬ LÝ FEEDBACK
# URL: POST /admin/api/feedback/process/{feedback_id}
# =========================================================
@router.post("/api/feedback/process/{feedback_id}")
async def mark_feedback_processed(
    feedback_id: int,
    admin: dict = Depends(require_admin),  # Bảo vệ API bằng require_admin
):
    try:
        supabase.table("feedbacks").update({"is_processed": True}).eq(
            "id", feedback_id
        ).execute()
        return JSONResponse(
            content={"success": True, "message": "Đã cập nhật trạng thái"}
        )
    except Exception as e:
        logger.error("Lỗi khi cập nhật feedback #%s: %s", feedback_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật trạng thái feedback",
        )