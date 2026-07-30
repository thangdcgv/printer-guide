from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import admin, home, guide, guide_step, auth, printer
from app.routers import dashboard
from fastapi.templating import Jinja2Templates
from app.routers import library

app = FastAPI(title="Thư viện hướng dẫn sử dụng máy in ", version="1.0.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(home.router)
app.include_router(admin.router)
app.include_router(guide.router)
app.include_router(guide_step.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(library.router)
app.include_router(printer.router)