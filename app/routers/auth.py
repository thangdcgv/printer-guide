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
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # Duy trì đăng nhập 7 ngày (604,800 giây)

ALLOWED_ADMIN_ROLES = {
    "Admin",
    "SuperAdmin",
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
    """
    Thiết lập cặp Cookie Access Token & Refresh Token vào Response.
    """
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
    """
    Xóa toàn bộ Session Cookie ở Client khi đăng xuất hoặc Session bị vô hiệu hóa.
    """
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
# HELPER: GET USER PROFILE
# =========================================================

def get_admin_profile(auth_id: str) -> Optional[dict]:
    """
    Lấy thông tin người dùng / quản trị viên dựa trên auth_id đã được Supabase Auth xác thực.
    """
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
        logger.error("Lỗi khi lấy thông tin admin profile: %s", exc)
        return None


# =========================================================
# HELPER: AUTHENTICATE USER & ADMIN SESSION (WITH AUTO-REFRESH)
# =========================================================

def authenticate_session(request: Request, response: Optional[Response] = None) -> Optional[dict]:
    """
    Xác thực session của BẤT KỲ tài khoản nào đã đăng nhập.
    Tự động dùng Refresh Token để gia hạn nếu Access Token bị hết hạn (sau 15 phút).
    """
    # Kiểm tra nếu Middleware đã xác thực trước đó
    if hasattr(request.state, "user_profile") and request.state.user_profile:
        return request.state.user_profile

    access_token = request.cookies.get(SESSION_COOKIE_NAME)
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)

    if not access_token and not refresh_token:
        return None

    auth_id: Optional[str] = None

    # 1. Thử xác thực với Access Token hiện tại
    if access_token:
        try:
            user_response = supabase.auth.get_user(access_token)
            if user_response and user_response.user:
                auth_id = user_response.user.id
        except Exception:
            auth_id = None

    # 2. Nếu Access Token hết hạn (sau 15 phút) -> Dùng Refresh Token để lấy Session mới
    if not auth_id and refresh_token:
        try:
            refresh_response = supabase.auth.refresh_session(refresh_token)
            if refresh_response and refresh_response.session and refresh_response.user:
                auth_id = refresh_response.user.id
                new_access_token = refresh_response.session.access_token
                new_refresh_token = refresh_response.session.refresh_token

                # Cập nhật Cookie mới ngay lập tức nếu có response object
                if response:
                    set_auth_cookies(response, new_access_token, new_refresh_token)
                
                logger.info("Tự động gia hạn Session thành công cho auth_id=%s", auth_id)
        except Exception as exc:
            logger.warning("Gia hạn session bằng Refresh Token thất bại: %s", exc)
            return None

    if not auth_id:
        return None

    # 3. Kiểm tra profile trong quan_tri_vien
    user_profile = get_admin_profile(auth_id)

    if not user_profile:
        logger.warning("Auth user không có profile hệ thống: auth_id=%s", auth_id)
        return None

    return user_profile


def authenticate_admin_session(request: Request, response: Optional[Response] = None) -> Optional[dict]:
    """
    Xác thực session VÀ kiểm tra xem tài khoản có quyền Admin/SuperAdmin hay không.
    """
    user_profile = authenticate_session(request, response)

    if not user_profile:
        return None

    role = user_profile.get("role")

    if role not in ALLOWED_ADMIN_ROLES:
        logger.warning("User không đủ quyền admin: auth_id=%s role=%s", user_profile.get("auth_id"), role)
        return None

    return user_profile


# =========================================================
# LOGIN PAGE
# =========================================================

@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    response: Response,
    error: Optional[str] = None,
):
    """GET /admin/login"""
    user = authenticate_session(request, response)

    # Nếu đã đăng nhập thì tự động chuyển hướng về trang tương ứng với role
    if user:
        user_role = user.get("role", "User")
        target_url = "/admin/guide" if user_role in ALLOWED_ADMIN_ROLES else "/"
        return RedirectResponse(
            url=target_url,
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

    # 1. Validation đầu vào
    if not clean_username or not clean_password:
        return render_login_error(
            request,
            "Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.",
            status.HTTP_400_BAD_REQUEST,
        )

    try:
        # 2. Xác định Email từ Username nhập vào
        target_email = clean_username

        if "@" not in clean_username:
            # Tra cứu Email trong bảng quan_tri_vien theo username
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
                # Dự phòng nếu username chưa khai báo trong DB: Tự động nối @gmail.com
                target_email = f"{clean_username.lower()}@gmail.com"

        # 3. Supabase Authentication
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

        # 4. Kiểm tra Profile trong cơ sở dữ liệu
        user_profile = get_admin_profile(user.id)

        if not user_profile:
            return render_login_error(
                request,
                "Tài khoản chưa được cấp quyền trên hệ thống.",
                status.HTTP_403_FORBIDDEN,
            )

        user_role = user_profile.get("role", "User")

        # 5. Điều hướng linh hoạt theo Role sau khi đăng nhập thành công
        target_url = "/admin/guide" if user_role in ALLOWED_ADMIN_ROLES else "/"

        # 6. Tạo Response & Thiết lập cặp Cookie (Access Token + Refresh Token)
        response = RedirectResponse(
            url=target_url,
            status_code=status.HTTP_303_SEE_OTHER,
        )

        set_auth_cookies(response, session.access_token, session.refresh_token)

        return response

    except Exception as exc:
        logger.warning("Đăng nhập thất bại: %s", exc)
        return render_login_error(request)


# =========================================================
# LOGOUT
# =========================================================

@router.api_route("/logout", methods=["GET", "POST"])
async def logout(request: Request):
    """
    Hỗ trợ đăng xuất bằng cả GET (thẻ <a>) lẫn POST (Form submit).
    """
    access_token = request.cookies.get(SESSION_COOKIE_NAME)

    # 1. Thu hồi session phía Supabase qua Admin API
    if access_token:
        try:
            # Sửa sign_out() thành admin.sign_out()
            supabase.auth.admin.sign_out(access_token)
        except Exception as exc:
            logger.warning("Không thể thu hồi token phía Supabase Auth: %s", exc)

    # 2. Redirect về trang Login
    response = RedirectResponse(
        url="/admin/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )

    # 3. Xóa cả 2 Cookie ở client
    clear_auth_cookies(response)

    return response


# =========================================================
# DEPENDENCIES
# =========================================================

async def require_login(request: Request, response: Response) -> dict:
    """
    Dependency bảo vệ các Route yêu cầu người dùng ĐÃ ĐĂNG NHẬP (Cả User & Admin).
    Nếu chưa đăng nhập sẽ bắn Exception để main.py tự động Redirect về /admin/login.
    """
    user = authenticate_session(request, response)

    if not user:
        raise AdminUnauthenticatedException()

    return user


async def require_admin(request: Request, response: Response) -> dict:
    """
    Dependency bảo vệ các Route chỉ dành riêng cho Quản trị viên (Admin / SuperAdmin).
    """
    admin = authenticate_admin_session(request, response)

    if not admin:
        raise AdminUnauthenticatedException()

    return admin