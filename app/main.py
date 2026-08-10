import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routers import (
    admin,
    auth,
    dashboard,
    guide,
    guide_step,
    home,
    library,
    printer,
)
# Cập nhật import Exception từ app.routers.admin
from app.routers.auth import AdminUnauthenticatedException

# =========================================================
# APPLICATION
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
# EXCEPTION HANDLERS
# =========================================================

@app.exception_handler(AdminUnauthenticatedException)
async def admin_unauthenticated_handler(
    request: Request,
    exc: AdminUnauthenticatedException,
):
    """
    Tự động xóa cookie hết hạn và chuyển hướng trình duyệt về /admin/login (303)
    khi người dùng chưa đăng nhập hoặc bị hủy Session.
    """
    response = RedirectResponse(
        url="/admin/login",
        status_code=303,
    )
    # Xóa sạch cookie rác/hết hạn trên trình duyệt client
    response.delete_cookie(key="admin_session", path="/")
    response.delete_cookie(key="admin_refresh", path="/")
    return response

# =========================================================
# TRUSTED HOST
# =========================================================

allowed_hosts = [
    "printer-guide.onrender.com",  # Domain Render
    "*.onrender.com",              # Subdomain Render (dự phòng)
    "localhost",                   # Test local
    "127.0.0.1",                   # Test local IP
    "[::1]",
]

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=allowed_hosts,
)

# =========================================================
# CORS
# =========================================================

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
# STATIC FILES
# =========================================================

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