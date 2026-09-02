import os
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.utils import track_user_visit, get_online_stats

from app.routers import (
    admin,
    auth,
    dashboard,
    guide,
    guide_step,
    home,
    library,
    printer,
    seo,
)
from app.routers.auth import (
    AdminUnauthenticatedException,
    SESSION_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    set_auth_cookies,
)
from app.database import supabase

# =========================================================
# APPLICATION (PHẢI KHỞI TẠO ĐẦU TIÊN)
# =========================================================

ENV = os.getenv("ENV", "development").lower()
IS_DEVELOPMENT = ENV == "development"

app = FastAPI(
    title="Thư viện hướng dẫn sử dụng máy in",
    version="1.0.0",
    docs_url="/docs" if IS_DEVELOPMENT else None,
    redoc_url="/redoc" if IS_DEVELOPMENT else None,
)

# =========================================================
# TRUSTED HOST & CORS
# =========================================================

allowed_hosts = [
    "printer-guide.onrender.com",
    "*.onrender.com",
    "localhost",
    "127.0.0.1",
    "192.168.100.40",
    "[::1]",
]

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=allowed_hosts,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://printer-guide.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# MIDDLEWARES (CHỦ Ý THỨ TỰ CHẠY)
# =========================================================

# 1. Middleware đếm Online Users (Khai báo trước -> Chạy SAU middleware Auth bên dưới)
@app.middleware("http")
async def count_online_users_middleware(request: Request, call_next):
    # Lấy user_id từ request.state (được gán bởi auth_session_middleware)
    user_id = getattr(request.state, "auth_id", None)
    
    # Ghi nhận thời gian active
    track_user_visit(request, user_id=user_id)
    
    response = await call_next(request)
    return response


# 2. Middleware Authenticate Session (Khai báo sau -> Chạy TRƯỚC để lấy user_id)
@app.middleware("http")
async def auth_session_middleware(request: Request, call_next):
    """
    Middleware nhẹ cho Public User: Chỉ xử lý Token nếu có, KHÔNG chặn request hay check DB ở đây.
    """
    access_token = request.cookies.get(SESSION_COOKIE_NAME)
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)

    new_tokens = None
    auth_id = None

    if access_token:
        try:
            user_res = supabase.auth.get_user(access_token)
            if user_res and user_res.user:
                auth_id = user_res.user.id
        except Exception:
            auth_id = None

    if not auth_id and refresh_token:
        try:
            refresh_res = supabase.auth.refresh_session(refresh_token)
            if refresh_res and refresh_res.session and refresh_res.user:
                auth_id = refresh_res.user.id
                new_tokens = (
                    refresh_res.session.access_token,
                    refresh_res.session.refresh_token,
                )
        except Exception:
            auth_id = None

    request.state.auth_id = auth_id
    response: Response = await call_next(request)

    if new_tokens:
        set_auth_cookies(response, new_tokens[0], new_tokens[1])

    return response

# =========================================================
# API & EXCEPTION HANDLERS
# =========================================================

@app.get("/api/admin/online-stats")
def api_online_stats():
    return get_online_stats()


@app.exception_handler(AdminUnauthenticatedException)
async def admin_unauthenticated_handler(
    request: Request,
    exc: AdminUnauthenticatedException,
):
    accept_header = request.headers.get("accept", "")
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    is_api_route = request.url.path.startswith("/api/") or "application/json" in accept_header

    if is_ajax or is_api_route:
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "success": False,
                "message": "Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại ở tab khác.",
            },
        )
    else:
        response = RedirectResponse(
            url="/admin/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/")
    return response

# =========================================================
# STATIC & PWA FILES
# =========================================================

@app.get("/sw.js", include_in_schema=False)
async def get_service_worker():
    return FileResponse("app/static/sw.js", media_type="application/javascript")


@app.get("/manifest.json", include_in_schema=False)
async def get_manifest():
    return FileResponse("app/static/manifest.json", media_type="application/manifest+json")


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.png", include_in_schema=False)
@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def favicon_fallback():
    favicon_path = "app/static/favicon.png"
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static",
)

# =========================================================
# ROUTERS
# =========================================================

app.include_router(home.router)
app.include_router(admin.router)
app.include_router(guide.router)
app.include_router(guide_step.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(library.router)
app.include_router(printer.router)
app.include_router(seo.router)