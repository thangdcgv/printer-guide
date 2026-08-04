from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])

templates = Jinja2Templates(directory="app/templates")


@router.get("")
async def admin_dashboard(request: Request):
    """
    Trang tổng quan Admin
    """
    # Lấy thông tin session/user từ cookie hiện tại
    user_session = request.cookies.get("user_session")
    
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "title": "Dashboard",
            "user": user_session  # Truyền biến user để base.html kiểm tra {% if user %}
        }
    )