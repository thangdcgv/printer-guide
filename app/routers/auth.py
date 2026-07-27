from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional

from app.database import supabase
from app.config import templates

router = APIRouter(prefix="/admin", tags=["Authentication"])

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    if request.cookies.get("user_session"):
        return RedirectResponse(url="/admin/guide", status_code=303)
    
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
            status_code=400
        )
    
    try:
        # 2. Tự động thêm @gmail.com nếu người dùng chỉ nhập tên viết tắt (không có @)
        target_email = clean_username
        if "@" not in target_email:
            target_email = f"{target_email}@gmail.com"

        # 3. Xác thực trực tiếp qua Supabase Auth với email hoàn chỉnh
        auth_response = supabase.auth.sign_in_with_password({
            "email": target_email,
            "password": clean_password
        })
        
        if not auth_response.user:
            raise Exception("Thông tin xác thực không hợp lệ")

        auth_id = auth_response.user.id

        # 4. Kiểm tra quyền hạn từ bảng quan_tri_vien
        profile_res = supabase.table("quan_tri_vien").select("*").eq("auth_id", auth_id).execute()
        
        if not profile_res.data:
            return templates.TemplateResponse(
                "admin_login.html",
                {"request": request, "error": "Tài khoản chưa được phân quyền trong hệ thống quản trị."},
                status_code=403
            )

        user_profile = profile_res.data[0]
        role = user_profile.get("role", "User")

        # 5. Lưu phiên đăng nhập vào Cookie và chuyển hướng
        response = RedirectResponse(url="/admin/guide", status_code=303)
        response.set_cookie(key="user_session", value=auth_id, httponly=True, max_age=86400)
        response.set_cookie(key="user_role", value=role, httponly=True, max_age=86400)

        return response

    except Exception as e:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Tên đăng nhập hoặc mật khẩu không chính xác."},
            status_code=400
        )

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("user_session")
    response.delete_cookie("user_role")
    try:
        supabase.auth.sign_out()
    except:
        pass
    return response
# --- HÀM KIỂM TRA QUYỀN TRUY CẬP ADMIN ---
async def require_admin(request: Request):
    user_session = request.cookies.get("user_session")
    if not user_session:
        # Nếu chưa có session đăng nhập, tự động chuyển hướng về trang login
        return RedirectResponse(url="/admin/login", status_code=303)