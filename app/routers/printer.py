from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.utils import normalize_text
from app.validators import validate_printer
from app.database import supabase

# Tự động gắn tiền tố /admin/printer cho toàn bộ route trong file này
router = APIRouter(prefix="/admin/printer", tags=["Printer Admin"])
templates = Jinja2Templates(directory="app/templates")


# 1. Danh sách máy in (GET /admin/printer)
@router.get("")
async def list_printer(request: Request, search: str = "", brand: str = ""):
    search = search.strip()
    brand = brand.strip()

    query = supabase.table("printer_model").select("*")

    if search:
        query = query.or_(f"brand.ilike.%{search}%,model.ilike.%{search}%")

    if brand:
        query = query.eq("brand", brand)

    result = query.order("brand").order("model").execute()

    brands_res = supabase.table("printer_model").select("brand").execute()
    brands_list = sorted(list(set(
        item["brand"] for item in (brands_res.data or []) if item.get("brand")
    )))

    return templates.TemplateResponse(
        "printer.html",
        {
            "request": request,
            "title": "Model máy in",
            "printers": result.data or [],
            "brands": brands_list,
            "search": search,
            "selected_brand": brand
        }
    )


# 2. Trang tạo mới (GET /admin/printer/create)
@router.get("/create")
async def printer_create(request: Request):
    return templates.TemplateResponse(
        "printer_create.html",
        {
            "request": request,
            "title": "Thêm Model",
            "errors": {},
            "brand": "",
            "model": "",
            "description": ""
        }
    )


# 3. Xử lý tạo mới (POST /admin/printer/create)
@router.post("/create")
async def printer_create_post(
    request: Request,
    brand: str = Form(...),
    model: str = Form(...),
    description: str = Form("")
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
                "description": description
            }
        )

    existing = (
        supabase
        .table("printer_model")
        .select("id")
        .ilike("brand", brand)
        .ilike("model", model)
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
                "description": description
            }
        )

    supabase.table("printer_model").insert({
        "brand": brand,
        "model": model,
        "description": description
    }).execute()

    return RedirectResponse(url="/admin/printer", status_code=status.HTTP_303_SEE_OTHER)


# 4. Trang chỉnh sửa (GET /admin/printer/edit/{id})
@router.get("/edit/{id}")
async def update_printer(request: Request, id: int):
    result = supabase.table("printer_model").select("*").eq("id", id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy model máy in")

    return templates.TemplateResponse(
        "printer_edit.html",
        {
            "request": request,
            "title": "Sửa Model",
            "printer": result.data[0],
            "errors": {}
        }
    )


# 5. Xử lý chỉnh sửa (POST /admin/printer/edit/{id})
@router.post("/edit/{id}")
async def printer_edit_post(
    request: Request,
    id: int,
    brand: str = Form(...),
    model: str = Form(...),
    description: str = Form("")
):
    brand = normalize_text(brand)
    model = normalize_text(model)
    description = description.strip()

    errors = validate_printer(brand, model)
    existing = (
        supabase
        .table("printer_model")
        .select("id")
        .ilike("brand", brand)
        .ilike("model", model)
        .neq("id", id)
        .execute()
    )

    if existing.data:
        errors = errors or {}
        errors["duplicate"] = "Model này đã tồn tại ở một bản ghi khác."

    if errors:
        return templates.TemplateResponse(
            "printer_edit.html",
            {
                "request": request,
                "title": "Sửa Model",
                "printer": {"id": id, "brand": brand, "model": model, "description": description},
                "errors": errors
            }
        )

    supabase.table("printer_model").update({
        "brand": brand,
        "model": model,
        "description": description
    }).eq("id", id).execute()

    return RedirectResponse(url="/admin/printer", status_code=status.HTTP_303_SEE_OTHER)


# 6. Xử lý xóa (POST /admin/printer/delete/{id})
@router.post("/delete/{id}")
async def printer_delete_post(id: int):
    supabase.table("printer_model").delete().eq("id", id).execute()
    return RedirectResponse(url="/admin/printer", status_code=status.HTTP_303_SEE_OTHER)