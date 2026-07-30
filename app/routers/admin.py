from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

# Thêm prefix="/admin" giúp mã nguồn ngắn gọn hơn
router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])

templates = Jinja2Templates(directory="app/templates")


# ==========================
# Dashboard (/admin)
# ==========================

@router.get("")
async def admin_dashboard(request: Request):
    """
    Trang tổng quan Admin.
    Sau này có thể bổ sung thống kê: Tổng số máy in, tổng số bài viết...
    """
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "title": "Dashboard"
        }
    )