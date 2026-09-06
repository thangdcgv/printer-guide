import os
import logging
import hashlib
from typing import Optional

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import templates
from app.database import supabase, supabase_admin

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Authentication"],
)

ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"

SESSION_COOKIE_NAME = "admin_session"
REFRESH_COOKIE_NAME = "admin_refresh"
SESSION_MAX_AGE = 60 * 60 * 24 * 7

ALLOWED_ADMIN_ROLES = {
    "admin",
    "super admin",
    "system admin",
}


class AdminUnauthenticatedException(Exception):
    pass


# =========================================================
# SESSION TRACKING HELPERS
# =========================================================

def _hash_token(token: str) -> str:
    """Băm token để lưu trữ và tra cứu an toàn trong DB."""
    return hashlib.sha256(token.encode()).hexdigest()


def register_user_session(auth_id: str, access_token: str, request: Request):
    try:
        token_hash = _hash_token(access_token)
        user_agent = request.headers.get("user-agent", "Unknown")
        client_ip = request.client.host if request.client else "Unknown"

        supabase_admin.table("user_sessions").insert({
            "auth_id": auth_id,
            "access_token_hash": token_hash,
            "user_agent": user_agent,
            "ip_address": client_ip,
        }).execute()
    except Exception as exc:
        logger.error(f"❌ Lỗi ghi nhận user session: {exc}")


def revoke_all_other_sessions(auth_id: str, current_token: Optional[str] = None):
    try:
        query = supabase_admin.table("user_sessions").delete().eq("auth_id", auth_id)
        if current_token:
            query = query.neq("access_token_hash", _hash_token(current_token))
        query.execute()
    except Exception as exc:
        logger.error(f"❌ Lỗi xoá session cũ: {exc}")


def revoke_current_session(access_token: str):
    """Xóa session cụ thể khi user bấm Logout."""
    try:
        token_hash = _hash_token(access_token)
        # ✅ FIX: Dùng supabase_admin tránh lỗi RLS khi Logout
        supabase_admin.table("user_sessions").delete().eq("access_token_hash", token_hash).execute()
    except Exception as exc:
        logger.error(f"❌ Lỗi xoá session hiện tại: {exc}")


# =========================================================
# COOKIE HELPERS
# =========================================================

def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
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
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/")


def render_login_error(
    request: Request,
    message: str = "Tên đăng nhập hoặc mật khẩu không chính xác.",
    status_code: int = status.HTTP_400_BAD_REQUEST,
):
    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "error": message,
        },
        status_code=status_code,
    )


def get_admin_profile(auth_id: str) -> Optional[dict]:
    try:
        # ✅ FIX: Dùng supabase_admin để luôn đọc được profile quản trị viên
        result = (
            supabase_admin
            .table("quan_tri_vien")
            .select("id, auth_id, username, email, ho_ten, role, nhan_vien_id, chuc_danh")
            .eq("auth_id", auth_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.error(f"❌ Lỗi khi lấy thông tin admin profile (auth_id={auth_id}): {exc}")
        return None


# =========================================================
# AUTHENTICATION DEPENDENCY
# =========================================================

def authenticate_session(request: Request, response: Optional[Response] = None) -> Optional[dict]:
    """Xác thực session và kiểm tra xem session có bị hủy từ thiết bị khác không."""
    if hasattr(request.state, "user_profile") and request.state.user_profile:
        return request.state.user_profile

    auth_id = getattr(request.state, "auth_id", None)
    access_token = request.cookies.get(SESSION_COOKIE_NAME)

    if not auth_id or not access_token:
        return None

    try:
        token_hash = _hash_token(access_token)
        session_check = (
            supabase_admin.table("user_sessions")
            .select("id")
            .eq("access_token_hash", token_hash)
            .limit(1)
            .execute()
        )
        if not session_check.data:
            return None
    except Exception as exc:
        return None

    user_profile = get_admin_profile(auth_id)
    if not user_profile:
        return None

    request.state.user_profile = user_profile
    return user_profile


def authenticate_admin_session(request: Request, response: Optional[Response] = None) -> Optional[dict]:
    user_profile = authenticate_session(request, response)
    if not user_profile:
        return None

    role = str(user_profile.get("role", "")).strip().lower()
    if role not in ALLOWED_ADMIN_ROLES:
        return None

    return user_profile


# =========================================================
# ROUTES
# =========================================================

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, response: Response, error: Optional[str] = None):
    admin_user = authenticate_admin_session(request, response)
    if admin_user:
        return RedirectResponse(url="/admin/guide", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse("admin_login.html", {"request": request, "error": error})


@router.post("/login")
def handle_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    login_action: Optional[str] = Form(None),
):
    """Xử lý đăng nhập và phát hiện xung đột thiết bị."""
    clean_username = username.strip()
    clean_password = password

    if not clean_username or not clean_password:
        return render_login_error(request, "Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.")

    try:
        target_email = clean_username
        if "@" not in clean_username:
            # ✅ FIX: Dùng supabase_admin để lookup email theo username
            lookup = (
                supabase_admin.table("quan_tri_vien")
                .select("email")
                .eq("username", clean_username)
                .limit(1)
                .execute()
            )
            target_email = lookup.data[0].get("email") if (lookup.data and lookup.data[0].get("email")) else f"{clean_username.lower()}@gmail.com"

        auth_response = supabase.auth.sign_in_with_password({"email": target_email, "password": clean_password})

        if not auth_response or not auth_response.user or not auth_response.session:
            return render_login_error(request)

        user = auth_response.user
        session = auth_response.session
        user_profile = get_admin_profile(user.id)

        if not user_profile:
            return render_login_error(request, "Tài khoản chưa được cấp quyền.", status.HTTP_403_FORBIDDEN)

        # ✅ FIX: Dùng supabase_admin kiểm tra session tồn tại
        existing_sessions = (
            supabase_admin.table("user_sessions")
            .select("id, user_agent, created_at")
            .eq("auth_id", user.id)
            .execute()
        )

        has_other_sessions = len(existing_sessions.data) > 0

        if has_other_sessions and not login_action:
            other_device_info = existing_sessions.data[0].get("user_agent", "Thiết bị khác")
            return templates.TemplateResponse(
                "admin_login.html",
                {
                    "request": request,
                    "show_conflict_warning": True,
                    "username": username,
                    "password": password,
                    "other_device_info": other_device_info,
                },
            )

        if login_action == "force_single":
            revoke_all_other_sessions(user.id)
        
        register_user_session(user.id, session.access_token, request)

        role = str(user_profile.get("role", "")).strip().lower()
        target_url = "/admin/guide" if role in ALLOWED_ADMIN_ROLES else "/"

        response = RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)
        set_auth_cookies(response, session.access_token, session.refresh_token)
        return response

    except Exception as exc:
        logger.warning(f"❌ Đăng nhập thất bại: {exc}")
        return render_login_error(request)


@router.api_route("/logout", methods=["GET", "POST"])
def logout(request: Request):
    access_token = request.cookies.get(SESSION_COOKIE_NAME)

    if access_token:
        revoke_current_session(access_token)
        try:
            supabase.auth.sign_out()
        except Exception as exc:
            logger.warning(f"⚠️ Không thể thu hồi token phía Supabase Auth: {exc}")

    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_auth_cookies(response)
    return response


def require_login(request: Request, response: Response) -> dict:
    user = authenticate_session(request, response)
    if not user:
        raise AdminUnauthenticatedException()
    return user


def require_admin(request: Request, response: Response) -> dict:
    admin = authenticate_admin_session(request, response)
    if not admin:
        raise AdminUnauthenticatedException()
    return admin