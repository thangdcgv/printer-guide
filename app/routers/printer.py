import logging
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.config import templates
from app.utils import normalize_text
from app.validators import validate_printer
from app.database import supabase
from app.routers.auth import require_login

logger = logging.getLogger(__name__)

# Tự động gắn tiền tố /admin/printer cho toàn bộ route trong file này
router = APIRouter(prefix="/admin/printer", tags=["Printer Admin"])


# 1. Danh sách máy in (GET /admin/printer)
@router.get("")
def list_printer(
    request: Request,
    search: str = "",
    brand: str = "",
    current_user: dict = Depends(require_login),
):
    search = search.strip()
    brand = brand.strip()

    query = supabase.table("printer_model").select("*")

    if search:
        query = query.or_(f"brand.ilike.%{search}%,model.ilike.%{search}%")

    if brand:
        query = query.eq("brand", brand)

    result = query.order("brand").order("model").execute()

    brands_res = supabase.table("printer_model").select("brand").execute()
    brands_list = sorted(
        list(
            set(
                item["brand"]
                for item in (brands_res.data or [])
                if item.get("brand")
            )
        )
    )

    return templates.TemplateResponse(
        "printer.html",
        {
            "request": request,
            "title": "Model máy in",
            "printers": result.data or [],
            "brands": brands_list,
            "search": search,
            "selected_brand": brand,
            "current_user": current_user,
            "admin": current_user,
        },
    )


# 2. Trang tạo mới (GET /admin/printer/create)
@router.get("/create")
def printer_create(
    request: Request,
    current_user: dict = Depends(require_login),
):
    return templates.TemplateResponse(
        "printer_create.html",
        {
            "request": request,
            "title": "Thêm Model",
            "errors": {},
            "brand": "",
            "model": "",
            "description": "",
            "current_user": current_user,
            "admin": current_user,
        },
    )


# 3. Xử lý tạo mới (POST /admin/printer/create)
@router.post("/create")
def printer_create_post(
    request: Request,
    brand: str = Form(...),
    model: str = Form(...),
    description: str = Form(""),
    current_user: dict = Depends(require_login),
):
    brand = normalize_text(brand)
    model = normalize_text(model)
    description = description.strip()

    errors = validate_printer(brand, model)
    if errors:
        return templates.TemplateResponse(
            "printer_create.html",
            {
                "request": request,
                "title": "Thêm Model",
                "errors": errors,
                "brand": brand,
                "model": model,
                "description": description,
                "current_user": current_user,
                "admin": current_user,
            },
        )

    # Kiểm tra trùng lặp model
    existing = (
        supabase.table("printer_model")
        .select("id")
        .eq("brand", brand)
        .eq("model", model)
        .execute()
    )

    if existing.data:
        return templates.TemplateResponse(
            "printer_create.html",
            {
                "request": request,
                "title": "Thêm Model",
                "errors": {"duplicate": "Model này đã tồn tại trong hệ thống."},
                "brand": brand,
                "model": model,
                "description": description,
                "current_user": current_user,
                "admin": current_user,
            },
        )

    supabase.table("printer_model").insert(
        {
            "brand": brand,
            "model": model,
            "description": description,
        }
    ).execute()

    return RedirectResponse(
        url="/admin/printer", status_code=status.HTTP_303_SEE_OTHER
    )


# 4. Trang chỉnh sửa (GET /admin/printer/edit/{id})
@router.get("/edit/{id}")
def update_printer(
    request: Request,
    id: int,
    current_user: dict = Depends(require_login),
):
    result = supabase.table("printer_model").select("*").eq("id", id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy model máy in")

    return templates.TemplateResponse(
        "printer_edit.html",
        {
            "request": request,
            "title": "Sửa Model",
            "printer": result.data[0],
            "errors": {},
            "current_user": current_user,
            "admin": current_user,
        },
    )


# 5. Xử lý chỉnh sửa (POST /admin/printer/edit/{id})
@router.post("/edit/{id}")
def printer_edit_post(
    request: Request,
    id: int,
    brand: str = Form(...),
    model: str = Form(...),
    description: str = Form(""),
    current_user: dict = Depends(require_login),
):
    brand = normalize_text(brand)
    model = normalize_text(model)
    description = description.strip()

    errors = validate_printer(brand, model) or {}

    existing = (
        supabase.table("printer_model")
        .select("id")
        .eq("brand", brand)
        .eq("model", model)
        .neq("id", id)
        .execute()
    )

    if existing.data:
        errors["duplicate"] = "Model này đã tồn tại ở một bản ghi khác."

    if errors:
        return templates.TemplateResponse(
            "printer_edit.html",
            {
                "request": request,
                "title": "Sửa Model",
                "printer": {
                    "id": id,
                    "brand": brand,
                    "model": model,
                    "description": description,
                },
                "errors": errors,
                "current_user": current_user,
                "admin": current_user,
            },
        )

    supabase.table("printer_model").update(
        {
            "brand": brand,
            "model": model,
            "description": description,
        }
    ).eq("id", id).execute()

    return RedirectResponse(
        url="/admin/printer", status_code=status.HTTP_303_SEE_OTHER
    )


# 6. Xử lý xóa (POST /admin/printer/delete/{id})
@router.post("/delete/{id}")
def printer_delete_post(
    id: int,
    current_user: dict = Depends(require_login),
):
    supabase.table("printer_model").delete().eq("id", id).execute()
    return RedirectResponse(
        url="/admin/printer", status_code=status.HTTP_303_SEE_OTHER
    )