import os
import logging
from typing import Optional

from fastapi import APIRouter, Form, Request, Response, status
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
REFRESH_COOKIE_NAME = "admin_refresh"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 ngày (604,800 giây)

# ✅ FIX LỖI 1: Chuẩn hóa toàn bộ role cho phép về chữ thường (lowercase)
ALLOWED_ADMIN_ROLES = {
    "admin",
    "super admin",
    "system admin",
}


# =========================================================
# CUSTOM EXCEPTION
# =========================================================

class AdminUnauthenticatedException(Exception):
    """
    Được raise khi: Chưa đăng nhập, token không hợp lệ, hoặc hết hạn.
    main.py sẽ catch exception này và redirect về /admin/login bằng HTTP 303.
    """
    pass


# =========================================================
# COOKIE HELPERS
# =========================================================

def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Thiết lập cặp Cookie Access Token & Refresh Token vào Response."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )


def clear_auth_cookies(response: Response) -> None:
    """Xóa toàn bộ Session Cookie ở Client khi đăng xuất."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/")


# =========================================================
# HELPER: LOGIN ERROR
# =========================================================

def render_login_error(
    request: Request,
    message: str = "Tên đăng nhập hoặc mật khẩu không chính xác.",
    status_code: int = status.HTTP_400_BAD_REQUEST,
):
    """Hiển thị lại trang login với thông báo lỗi chung."""
    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "error": message,
        },
        status_code=status_code,
    )


# =========================================================
# HELPER: GET USER PROFILE
# =========================================================

def get_admin_profile(auth_id: str) -> Optional[dict]:
    """Lấy thông tin profile quản trị viên dựa trên auth_id."""
    try:
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
    except Exception as exc:
        logger.error(f"❌ Lỗi khi lấy thông tin admin profile (auth_id={auth_id}): {exc}")
        return None


# =========================================================
# HELPER: AUTHENTICATE USER & ADMIN SESSION
# =========================================================

def authenticate_session(request: Request, response: Optional[Response] = None) -> Optional[dict]:
    """Xác thực session từ request.state do Middleware thiết lập."""
    if hasattr(request.state, "user_profile") and request.state.user_profile:
        return request.state.user_profile

    auth_id = getattr(request.state, "auth_id", None)
    if not auth_id:
        return None

    user_profile = get_admin_profile(auth_id)
    if not user_profile:
        logger.warning(f"⚠️ Auth user không có profile hệ thống: auth_id={auth_id}")
        return None

    request.state.user_profile = user_profile
    return user_profile


def authenticate_admin_session(request: Request, response: Optional[Response] = None) -> Optional[dict]:
    """Xác thực người dùng và kiểm tra quyền Admin."""
    user_profile = authenticate_session(request, response)

    if not user_profile:
        return None

    role = str(user_profile.get("role", "")).strip().lower()

    if role not in ALLOWED_ADMIN_ROLES:
        logger.warning(f"⛔ User không đủ quyền admin: auth_id={user_profile.get('auth_id')}, role={role}")
        return None

    return user_profile


# =========================================================
# LOGIN PAGE
# =========================================================

@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    response: Response,
    error: Optional[str] = None,
):
    """GET /admin/login"""
    admin_user = authenticate_admin_session(request, response)

    if admin_user:
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
def handle_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """POST /admin/login"""
    clean_username = username.strip()
    clean_password = password

    if not clean_username or not clean_password:
        return render_login_error(
            request,
            "Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.",
            status.HTTP_400_BAD_REQUEST,
        )

    try:
        target_email = clean_username

        if "@" not in clean_username:
            lookup = (
                supabase.table("quan_tri_vien")
                .select("email")
                .eq("username", clean_username)
                .limit(1)
                .execute()
            )

            if lookup.data and lookup.data[0].get("email"):
                target_email = lookup.data[0].get("email")
            else:
                target_email = f"{clean_username.lower()}@gmail.com"

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

        user_profile = get_admin_profile(user.id)

        if not user_profile:
            return render_login_error(
                request,
                "Tài khoản chưa được cấp quyền trên hệ thống.",
                status.HTTP_403_FORBIDDEN,
            )

        role = str(user_profile.get("role", "")).strip().lower()
        target_url = "/admin/guide" if role in ALLOWED_ADMIN_ROLES else "/"

        response = RedirectResponse(
            url=target_url,
            status_code=status.HTTP_303_SEE_OTHER,
        )

        set_auth_cookies(response, session.access_token, session.refresh_token)
        return response

    except Exception as exc:
        logger.warning(f"❌ Đăng nhập thất bại: {exc}")
        return render_login_error(request)


# =========================================================
# LOGOUT
# =========================================================

@router.api_route("/logout", methods=["GET", "POST"])
def logout(request: Request):
    """Đăng xuất người dùng và thu hồi Cookie/Session."""
    access_token = request.cookies.get(SESSION_COOKIE_NAME)

    if access_token:
        try:
            # ✅ FIX LỖI 2: Đăng xuất an toàn bằng API chính thức của Supabase Client
            supabase.auth.sign_out()
        except Exception as exc:
            logger.warning(f"⚠️ Không thể thu hồi token phía Supabase Auth: {exc}")

    response = RedirectResponse(
        url="/admin/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )

    clear_auth_cookies(response)
    return response


# =========================================================
# DEPENDENCIES
# =========================================================

def require_login(request: Request, response: Response) -> dict:
    """Dependency bảo vệ các Route yêu cầu người dùng ĐÃ ĐĂNG NHẬP."""
    user = authenticate_session(request, response)
    if not user:
        raise AdminUnauthenticatedException()
    return user


def require_admin(request: Request, response: Response) -> dict:
    """Dependency bảo vệ các Route chỉ dành riêng cho Quản trị viên."""
    admin = authenticate_admin_session(request, response)
    if not admin:
        raise AdminUnauthenticatedException()
    return admin