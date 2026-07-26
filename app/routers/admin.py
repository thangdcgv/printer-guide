from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.utils import normalize_text
from app.validators import validate_printer
from app.database import supabase

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


# ==========================
# Dashboard
# ==========================

@router.get("/admin")
async def admin(request: Request):
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "title": "Dashboard"
        }
    )


# ==========================
# Printer List
# ==========================

@router.get("/admin/printer")
async def list_printer(request: Request):
    result = (
        supabase
        .table("printer_model")
        .select("*")
        .order("brand")
        .order("model")
        .execute()
    )

    return templates.TemplateResponse(
        "printer.html",
        {
            "request": request,
            "title": "Model máy in",
            "printers": result.data or []
        }
    )


# ==========================
# Create Printer (GET)
# ==========================

@router.get("/admin/printer/create")
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


# ==========================
# Create Printer (POST)
# ==========================

@router.post("/admin/printer/create")
async def printer_create_post(
    request: Request,
    brand: str = Form(...),
    model: str = Form(...),
    description: str = Form("")
):
    # Chuẩn hóa dữ liệu
    brand = normalize_text(brand)
    model = normalize_text(model)
    description = description.strip()

    # Kiểm tra dữ liệu hợp lệ
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

    # Kiểm tra trùng Brand + Model
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

    # Lưu dữ liệu
    supabase.table("printer_model").insert(
        {
            "brand": brand,
            "model": model,
            "description": description
        }
    ).execute()

    return RedirectResponse(
        url="/admin/printer",
        status_code=status.HTTP_303_SEE_OTHER
    )


# ==========================
# Edit Printer (GET)
# ==========================

@router.get("/admin/printer/edit/{id}")
async def update_printer(request: Request, id: int):
    # Lấy thông tin model máy in
    result = (
        supabase
        .table("printer_model")
        .select("*")
        .eq("id", id)
        .execute()
    )

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


# ==========================
# Edit Printer (POST)
# ==========================

@router.post("/admin/printer/edit/{id}")
async def printer_edit_post(
    request: Request,
    id: int,
    brand: str = Form(...),
    model: str = Form(...),
    description: str = Form("")
):
    # Chuẩn hóa dữ liệu đầu vào
    brand = normalize_text(brand)
    model = normalize_text(model)
    description = description.strip()

    # Validate dữ liệu
    errors = validate_printer(brand, model)

    # Kiểm tra trùng lặp với các record KHÁC (neq id)
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
                "printer": {
                    "id": id,
                    "brand": brand,
                    "model": model,
                    "description": description
                },
                "errors": errors
            }
        )

    # Cập nhật DB
    supabase.table("printer_model").update(
        {
            "brand": brand,
            "model": model,
            "description": description
        }
    ).eq("id", id).execute()

    return RedirectResponse(
        url="/admin/printer",
        status_code=status.HTTP_303_SEE_OTHER
    )
# ==========================
# Guide List (Admin)
# ==========================

@router.get("/admin/guide")
async def list_guide_admin(request: Request):

    # ==========================
    # Lấy tham số bộ lọc
    # ==========================

    search = request.query_params.get("search", "")
    printer_model_id = request.query_params.get("printer_model_id")
    status = request.query_params.get("status")


    # ==========================
    # Query dữ liệu
    # ==========================

    query = (
        supabase
        .table("guide")
        .select(
            "*, printer_model:printer_model_id(brand, model)"
        )
    )


    # ==========================
    # Lọc theo trạng thái
    # ==========================

    if status == "1":
        query = query.eq("is_active", True)

    elif status == "0":
        query = query.eq("is_active", False)



    # ==========================
    # Lọc theo model máy in
    # ==========================

    if printer_model_id:
        query = query.eq(
            "printer_model_id",
            int(printer_model_id)
        )



    # ==========================
    # Lọc tìm kiếm
    # ==========================

    if search:

        query = query.or_(
            f"title.ilike.%{search}%,description.ilike.%{search}%"
        )



    result = (
        query
        .order("sort_order")
        .order("id", desc=True)
        .execute()
    )



    # ==========================
    # Load danh sách máy in
    # cho dropdown
    # ==========================

    printers = (
        supabase
        .table("printer_model")
        .select("id, brand, model")
        .order("brand")
        .order("model")
        .execute()
    )


    return templates.TemplateResponse(
        "guide.html",
        {
            "request": request,
            "title": "Quản lý bài viết Hướng dẫn",

            "guide": result.data or [],

            # dữ liệu filter
            "printers": printers.data or [],

            "search": search,

            "selected_printer_id": printer_model_id,

            "status": status
        }
    )


# ==========================
# Create Guide (GET)
# ==========================

@router.get("/admin/guide/create")
async def guide_create(request: Request):
    # Lấy danh sách máy in để hiện dropdown chọn model tương ứng
    printers = (
        supabase
        .table("printer_model")
        .select("id, brand, model")
        .order("brand")
        .order("model")
        .execute()
    )

    return templates.TemplateResponse(
        "guide_create.html",
        {
            "request": request,
            "title": "Thêm Bài Hướng Dẫn",
            "printers": printers.data or [],
            "errors": {},
            "guide": {}
        }
    )


# ==========================
# Create Guide (POST)
# ==========================

@router.post("/admin/guide/create")
async def guide_create_post(
    request: Request,
    title: str = Form(...),
    printer_model_id: int = Form(...),
    description: str = Form(...)
):
    title = title.strip()
    description = description.strip()

    errors = {}
    if not title:
        errors["title"] = "Tiêu đề không được để trống."
    if not description:
        errors["description"] = "Nội dung bài viết không được để trống."

    if errors:
        printers = supabase.table("printer_model").select("id, brand, model").execute()
        return templates.TemplateResponse(
            "guide_create.html",
            {
                "request": request,
                "title": "Thêm Bài Hướng Dẫn",
                "printers": printers.data or [],
                "errors": errors,
                "guide": {
                    "title": title,
                    "printer_model_id": printer_model_id,
                    "description": description
                }
            }
        )

    # Lưu bài viết mới vào DB
    supabase.table("guide").insert({
        "title": title,
        "printer_model_id": printer_model_id,
        "description": description
    }).execute()

    return RedirectResponse(
        url="/admin/guide",
        status_code=status.HTTP_303_SEE_OTHER
    )


# ==========================
# Edit Guide (GET)
# ==========================

@router.get("/admin/guide/edit/{id}")
async def guide_edit(request: Request, id: int):
    guide_res = (
        supabase
        .table("guide")
        .select("*")
        .eq("id", id)
        .execute()
    )

    if not guide_res.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")

    printers = (
        supabase
        .table("printer_model")
        .select("id, brand, model")
        .order("brand")
        .execute()
    )

    return templates.TemplateResponse(
        "guide_edit.html",
        {
            "request": request,
            "title": "Sửa Bài Hướng Dẫn",
            "guide": guide_res.data[0],
            "printers": printers.data or [],
            "errors": {}
        }
    )


# ==========================
# Edit Guide (POST)
# ==========================

@router.post("/admin/guide/edit/{id}")
async def guide_edit_post(
    request: Request,
    id: int,
    title: str = Form(...),
    printer_model_id: int = Form(...),
    description: str = Form(...)
    
):
    title = title.strip()
    description = description.strip()

    errors = {}
    if not title:
        errors["title"] = "Tiêu đề không được để trống."
    if not description:
        errors["description"] = "Nội dung không được để trống."

    if errors:
        printers = supabase.table("printer_model").select("id, brand, model").execute()
        return templates.TemplateResponse(
            "guide_edit.html",
            {
                "request": request,
                "title": "Sửa Bài Hướng Dẫn",
                "printers": printers.data or [],
                "errors": errors,
                "guide": {
                    "id": id,
                    "title": title,
                    "printer_model_id": printer_model_id,
                    "description": description
                  
                }
            }
        )

    # Cập nhật thông tin bài viết
    supabase.table("guide").update({
        "title": title,
        "printer_model_id": printer_model_id,
        "description": description
       
    }).eq("id", id).execute()

    return RedirectResponse(
        url="/admin/guide",
        status_code=status.HTTP_303_SEE_OTHER
    )


# ==========================
# Delete Guide (POST)
# ==========================

@router.post("/admin/guide/delete/{id}")
async def guide_delete_post(id: int):
    supabase.table("guide").delete().eq("id", id).execute()
    return RedirectResponse(
        url="/admin/guide",
        status_code=status.HTTP_303_SEE_OTHER
    )