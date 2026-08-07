import logging
from typing import Optional
from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import supabase
from app.config import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Authentication"])

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    # Nếu đã có cookie đăng nhập, chuyển hướng thẳng vào admin
    if request.cookies.get("user_session"):
        return RedirectResponse(url="/admin/guide", status_code=status.HTTP_303_SEE_OTHER)
    
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": error}
    )

@router.post("/login")
async def handle_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    clean_username = username.strip()
    clean_password = password.strip()

    # 1. Validation cơ bản phía server
    if not clean_username or not clean_password:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu."},
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        target_email = clean_username

        # 2. Xử lý thông minh: Nếu người dùng nhập username (không có @), tra cứu email từ DB
        if "@" not in target_email:
            user_lookup = supabase.table("quan_tri_vien").select("email").eq("username", target_email).execute()
            if user_lookup.data and len(user_lookup.data) > 0:
                target_email = user_lookup.data[0]["email"]
            else:
                # Mặc định thêm domain nếu không tìm thấy username trong DB
                target_email = f"{target_email}@gmail.com"

        # 3. Xác thực trực tiếp qua Supabase Auth
        auth_response = supabase.auth.sign_in_with_password({
            "email": target_email,
            "password": clean_password
        })
        
        if not auth_response or not auth_response.user:
            raise Exception("Thông tin xác thực Supabase không hợp lệ")

        auth_id = auth_response.user.id

        # 4. Kiểm tra hồ sơ và quyền hạn từ bảng quan_tri_vien
        profile_res = supabase.table("quan_tri_vien").select("*").eq("auth_id", auth_id).execute()
        
        if not profile_res.data:
            return templates.TemplateResponse(
                "admin_login.html",
                {"request": request, "error": "Tài khoản chưa được phân quyền trong hệ thống quản trị."},
                status_code=status.HTTP_403_FORBIDDEN
            )

        user_profile = profile_res.data[0]
        role = user_profile.get("role", "User")

        # 5. Lưu cookie phiên đăng nhập
        response = RedirectResponse(url="/admin/guide", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user_session", value=auth_id, httponly=True, max_age=86400)
        response.set_cookie(key="user_role", value=role, httponly=True, max_age=86400)

        return response

    except Exception as e:
        logger.error(f"❌ Lỗi đăng nhập: {e}")
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Tên đăng nhập hoặc mật khẩu không chính xác."},
            status_code=status.HTTP_400_BAD_REQUEST
        )

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("user_session")
    response.delete_cookie("user_role")
    try:
        supabase.auth.sign_out()
    except Exception as e:
        logger.warning(f"Lỗi sign_out Supabase Auth: {e}")
    return response


# =========================================================
# HÀM DEPENDENCY KIỂM TRA QUYỀN TRUY CẬP ADMIN & TRẢ VỀ USER DICT
# =========================================================
async def require_admin(request: Request) -> dict:
    """
    Dependency dùng cho Depends(require_admin):
    - Trả về dict thông tin quản trị viên đầy đủ (id, auth_id, email, ho_ten, role,...).
    - Tự động raise HTTPException(303) để redirect về trang login nếu chưa đăng nhập.
    """
    auth_id = request.cookies.get("user_session")
    
    if not auth_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/login"}
        )

    try:
        # Tra cứu hồ sơ admin dựa trên auth_id lưu ở cookie
        res = supabase.table("quan_tri_vien").select("*").eq("auth_id", auth_id).execute()
        
        if not res.data or len(res.data) == 0:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/admin/login"}
            )

        user_data = res.data[0]
        return user_data  # 🟢 TRẢ VỀ DICT DỮ LIỆU USER ĐỂ CÁC ROUTE KHÁC SỬ DỤNG

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Lỗi xác thực require_admin: {e}")
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/login"}
        )