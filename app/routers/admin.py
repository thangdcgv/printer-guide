import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import templates
from app.database import supabase
# Nên đổi sang require_admin cho các chức năng quản trị nhạy cảm
from app.routers.auth import require_admin, require_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Hub"])


# =========================================================
# 1. TRANG QUẢN TRỊ TRUNG TÂM (HIỂN THỊ admin.html)
# URL: GET /admin
# =========================================================
@router.get("", response_class=HTMLResponse)
async def admin_main(
    request: Request,
    response: Response,
    current_user: dict = Depends(require_login),
):
    """
    Trang Hub chính hiển thị các card chức năng
    """
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "current_user": current_user,
            "admin": current_user,  # 👉 BỔ SUNG DÒNG NÀY ĐỂ FIX LỖI HTML
        },
    )

# =========================================================
# 3. API ĐÁNH DẤU XỬ LÝ FEEDBACK
# URL: POST /admin/api/feedback/process/{feedback_id}
# =========================================================
@router.post("/api/feedback/process/{feedback_id}")
async def mark_feedback_processed(
    feedback_id: int,
    current_user: dict = Depends(require_admin),  # Khuyến nghị dùng require_admin
):
    try:
        supabase.table("feedbacks").update({"is_processed": True}).eq(
            "id", feedback_id
        ).execute()
        return JSONResponse(
            content={"success": True, "message": "Đã cập nhật trạng thái thành công"}
        )
    except Exception as e:
        logger.error("Lỗi khi cập nhật feedback #%s: %s", feedback_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật trạng thái feedback",
        )