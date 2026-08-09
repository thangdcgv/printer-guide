import os
import logging
from typing import Optional

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import templates
from app.database import supabase

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Authentication"],
)

# =========================================================
# CONFIG
# =========================================================

ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"

SESSION_COOKIE_NAME = "admin_session"
SESSION_MAX_AGE = 60 * 60  # Cookie tồn tại tối đa 1 giờ

ALLOWED_ADMIN_ROLES = {
    "Admin",
    "SuperAdmin",
}


# =========================================================
# CUSTOM EXCEPTION
# =========================================================

class AdminUnauthenticatedException(Exception):
    """
    Được raise khi: Chưa đăng nhập, token không hợp lệ, hết hạn, hoặc không có quyền admin.
    main.py sẽ catch exception này và redirect về /admin/login bằng HTTP 303.
    """
    pass


# =========================================================
# HELPER: LOGIN ERROR
# =========================================================

def render_login_error(
    request: Request,
    message: str = "Tên đăng nhập hoặc mật khẩu không chính xác.",
    status_code: int = status.HTTP_400_BAD_REQUEST,
):
    """
    Hiển thị lại trang login với thông báo lỗi chung.
    Tránh làm lộ sự tồn tại của username/email để phòng ngừa dò quét tài khoản.
    """
    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "error": message,
        },
        status_code=status_code,
    )


# =========================================================
# HELPER: GET ADMIN PROFILE
# =========================================================

def get_admin_profile(auth_id: str) -> Optional[dict]:
    """
    Lấy thông tin quản trị viên dựa trên auth_id đã được Supabase Auth xác thực.
    Không truy vấn ma_truy_cap để đảm bảo an toàn dữ liệu.
    """
    result = (
        supabase
        .table("quan_tri_vien")
        .select(
            """
            id,
            auth_id,
            username,
            email,
            ho_ten,
            role,
            nhan_vien_id,
            chuc_danh,
            ngay_sinh,
            so_dien_thoai,
            dia_chi,
            nguoi_quan_ly_id
            """
        )
        .eq("auth_id", auth_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    return result.data[0]


# =========================================================
# HELPER: AUTHENTICATE ADMIN SESSION
# =========================================================

def authenticate_admin_session(request: Request) -> Optional[dict]:
    """
    Xác thực session admin.
    Flow: Cookie -> access_token -> Supabase Auth -> auth_id -> quan_tri_vien -> role -> Valid Admin
    """
    access_token = request.cookies.get(SESSION_COOKIE_NAME)

    if not access_token:
        return None

    try:
        # 1. Xác thực access token với Supabase
        user_response = supabase.auth.get_user(access_token)

        if not user_response or not user_response.user:
            return None

        auth_user = user_response.user
        auth_id = auth_user.id

        # 2. Kiểm tra profile trong quan_tri_vien
        admin = get_admin_profile(auth_id)

        if not admin:
            logger.warning("Auth user không có profile admin: auth_id=%s", auth_id)
            return None

        # 3. Kiểm tra role
        role = admin.get("role")

        if role not in ALLOWED_ADMIN_ROLES:
            logger.warning("User không đủ quyền admin: auth_id=%s role=%s", auth_id, role)
            return None

        return admin

    except Exception as exc:
        logger.info("Admin session không hợp lệ: %s", exc)
        return None


# =========================================================
# LOGIN PAGE
# =========================================================

@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: Optional[str] = None,
):
    """GET /admin/login"""
    admin = authenticate_admin_session(request)

    # Nếu đã đăng nhập thì tự động chuyển vào trang quản trị
    if admin:
        return RedirectResponse(
            url="/admin/guide",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "error": error,
        },
    )


# =========================================================
# HANDLE LOGIN
# =========================================================

@router.post("/login")
async def handle_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """POST /admin/login"""
    clean_username = username.strip()
    clean_password = password  # Mật khẩu giữ nguyên khoảng trắng hợp lệ

    # Validation cơ bản
    if not clean_username or not clean_password:
        return render_login_error(
            request,
            "Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.",
            status.HTTP_400_BAD_REQUEST,
        )

    try:
        # 1. Xác định email
        target_email = clean_username

        if "@" not in clean_username:
            lookup = (
                supabase
                .table("quan_tri_vien")
                .select("email")
                .eq("username", clean_username)
                .limit(1)
                .execute()
            )

            if not lookup.data:
                return render_login_error(request)

            target_email = lookup.data[0].get("email")

            if not target_email:
                return render_login_error(request)

        # 2. Supabase Authentication
        auth_response = supabase.auth.sign_in_with_password(
            {
                "email": target_email,
                "password": clean_password,
            }
        )

        if not auth_response or not auth_response.user or not auth_response.session:
            return render_login_error(request)

        user = auth_response.user
        session = auth_response.session

        # 3. Kiểm tra Admin Profile & Role
        admin = get_admin_profile(user.id)

        if not admin:
            return render_login_error(
                request,
                "Tài khoản chưa được cấp quyền quản trị.",
                status.HTTP_403_FORBIDDEN,
            )

        if admin.get("role") not in ALLOWED_ADMIN_ROLES:
            return render_login_error(
                request,
                "Tài khoản không có quyền truy cập khu vực quản trị.",
                status.HTTP_403_FORBIDDEN,
            )

        # 4. Tạo Response & Thiết lập Cookie
        response = RedirectResponse(
            url="/admin/guide",
            status_code=status.HTTP_303_SEE_OTHER,
        )

        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session.access_token,
            httponly=True,
            secure=IS_PRODUCTION,
            samesite="lax",
            path="/",
            max_age=SESSION_MAX_AGE,
        )

        return response

    except Exception as exc:
        logger.warning("Đăng nhập thất bại: %s", exc)
        return render_login_error(request)


# =========================================================
# LOGOUT
# =========================================================

# Sửa decorator từ @router.post("/logout") thành @router.api_route
@router.api_route("/logout", methods=["GET", "POST"])
async def logout(request: Request):
    """
    Hỗ trợ đăng xuất bằng cả GET (thẻ <a>) lẫn POST (Form submit).
    """
    access_token = request.cookies.get(SESSION_COOKIE_NAME)

    # 1. Thu hồi session phía Supabase
    if access_token:
        try:
            supabase.auth.sign_out(access_token)
        except Exception as exc:
            logger.warning("Không thể thu hồi token phía Supabase Auth: %s", exc)

    # 2. Redirect về trang Login
    response = RedirectResponse(
        url="/admin/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )

    # 3. Xóa Cookie ở client
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
    )

    return response


# =========================================================
# REQUIRE ADMIN DEPENDENCY
# =========================================================

async def require_admin(request: Request) -> dict:
    """
    Dependency bảo vệ các Route Admin.
    Nếu không hợp lệ sẽ bắn Exception để main.py tự động Redirect.
    """
    admin = authenticate_admin_session(request)

    if not admin:
        raise AdminUnauthenticatedException()

    return admin