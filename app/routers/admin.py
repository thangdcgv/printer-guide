import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import templates
from app.database import supabase
from app.routers.auth import require_admin, require_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Hub"])


# =========================================================
# 1. TRANG QUẢN TRỊ TRUNG TÂM
# URL: GET /admin
# =========================================================
@router.get("", response_class=HTMLResponse)
def admin_main(
    request: Request,
    response: Response,
    current_user: dict = Depends(require_admin), # Đổi sang require_admin để bảo mật
):
    """
    Trang Hub chính hiển thị các card chức năng quản trị.
    Dùng 'def' để tránh block Async Event Loop khi render template.
    """
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "current_user": current_user,
            "admin": current_user,
        },
    )


# =========================================================
# 2. API LẤY DANH SÁCH FEEDBACK (PHÂN TRANG & LỌC)
# URL: GET /admin/api/feedbacks
# =========================================================
@router.get("/api/feedbacks")
def get_feedbacks(
    is_processed: Optional[bool] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(require_admin),
):
    """Lấy danh sách phản hồi từ người dùng cho Admin Dashboard."""
    try:
        query = supabase.table("feedbacks").select("*", count="exact")
        
        if is_processed is not None:
            query = query.eq("is_processed", is_processed)
            
        res = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        
        return {
            "success": True,
            "data": res.data or [],
            "total": res.count or 0
        }
    except Exception as e:
        logger.error(f"❌ Lỗi khi lấy danh sách feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lấy danh sách phản hồi"
        )


# =========================================================
# 3. API ĐÁNH DẤU XỬ LÝ FEEDBACK
# URL: POST /admin/api/feedback/process/{feedback_id}
# =========================================================
@router.post("/api/feedback/process/{feedback_id}")
def mark_feedback_processed(
    feedback_id: int,
    current_user: dict = Depends(require_admin),
):
    """Đánh dấu một phản hồi đã được xử lý."""
    try:
        res = supabase.table("feedbacks").update({"is_processed": True}).eq(
            "id", feedback_id
        ).execute()
        
        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy ID phản hồi"
            )

        return JSONResponse(
            content={"success": True, "message": "Đã cập nhật trạng thái thành công"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("❌ Lỗi khi cập nhật feedback #%s: %s", feedback_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật trạng thái feedback",
        )


# =========================================================
# 4. API XÓA FEEDBACK
# URL: DELETE /admin/api/feedback/{feedback_id}
# =========================================================
@router.delete("/api/feedback/{feedback_id}")
def delete_feedback(
    feedback_id: int,
    current_user: dict = Depends(require_admin),
):
    """Xóa phản hồi rác/spam."""
    try:
        supabase.table("feedbacks").delete().eq("id", feedback_id).execute()
        return JSONResponse(
            content={"success": True, "message": "Đã xóa phản hồi thành công"}
        )
    except Exception as e:
        logger.error("❌ Lỗi khi xóa feedback #%s: %s", feedback_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể xóa phản hồi",
        )