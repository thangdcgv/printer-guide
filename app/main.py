from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.routers import admin, home, guide, guide_step, auth, printer, dashboard, library

app = FastAPI(title="Thư viện hướng dẫn sử dụng máy in", version="1.0.0")

# Mount thư mục chứa file tĩnh (CSS, JS, Images)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Khai báo Templates
templates = Jinja2Templates(directory="app/templates")

# Đăng ký các Router
app.include_router(home.router)
app.include_router(admin.router)
app.include_router(guide.router)
app.include_router(guide_step.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(library.router)
app.include_router(printer.router)
