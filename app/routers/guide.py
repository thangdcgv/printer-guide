import os
import uuid
from typing import Optional
from fastapi import APIRouter, Request, Form, UploadFile, File, status, HTTPException, Depends
from app.routers.auth import require_admin

from fastapi import (
    APIRouter,
    Request,
    Form,
    UploadFile,
    File,
    status,
    HTTPException
)

from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import supabase


router = APIRouter(
    prefix="/admin/guide",
    tags=["guide"],
    dependencies=[Depends(require_admin)] # <--- Khóa toàn bộ các route quản lý bài viết lớn
)

templates = Jinja2Templates(
    directory="app/templates"
)


UPLOAD_DIR = "app/static/images"

ALLOWED_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".webp"
]


# =====================================================
# IMAGE FUNCTIONS
# =====================================================

async def save_image(image: UploadFile):

    if not image or not image.filename:
        return None


    ext = os.path.splitext(image.filename)[1].lower()


    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Chỉ cho phép file jpg, jpeg, png, webp"
        )


    filename = f"{uuid.uuid4().hex}{ext}"

    os.makedirs(
        UPLOAD_DIR,
        exist_ok=True
    )


    filepath = os.path.join(
        UPLOAD_DIR,
        filename
    )


    content = await image.read()


    with open(filepath, "wb") as f:
        f.write(content)


    return f"/static/images/{filename}"




# =====================================================
# LIST
# =====================================================

@router.get("/", response_class=HTMLResponse)
async def list_guides(
    request: Request,
    search: Optional[str] = None,
    printer_model_id: Optional[str] = None,
    guide_status: Optional[str] = None
):
    query = (
        supabase
        .table("guide")
        .select("*")
    )

    if search:
        query = query.ilike(
            "title",
            f"%{search.strip()}%"
        )

    if printer_model_id and printer_model_id.isdigit():
        query = query.eq(
            "printer_model_id",
            int(printer_model_id)
        )

    if guide_status in ["0", "1"]:
        query = query.eq(
            "is_active",
            guide_status == "1"
        )

    guides_res = (
        query
        .order("sort_order")
        .order("id", desc=True)
        .execute()
    )

    guides = guides_res.data or []

    printers_res = (
        supabase
        .table("printer_model")
        .select(
            "id, brand, model"
        )
        .order("brand")
        .order("model")
        .execute()
    )

    printers = printers_res.data or []

    printer_map = {
        p["id"]: p
        for p in printers
    }

    # Danh sách các hãng có thiết kế nhận diện riêng (có thể mở rộng thoải mái)
    known_brands = ["brother", "canon", "epson", "hp"]

    for g in guides:
        p_id = g.get("printer_model_id")
        p = printer_map.get(p_id)
        
        if p:
            # Tạo bản sao để tránh làm thay đổi trực tiếp dữ liệu gốc của dictionary printer
            p_data = p.copy()
            brand_lower = p_data.get("brand", "").strip().lower()
            
            # Tự động quét và gán class CSS động, nếu hãng mới sẽ tự động rơi vào "other"
            matched_class = "other"
            for kb in known_brands:
                if kb in brand_lower:
                    matched_class = kb
                    break
            
            p_data["brand_class"] = f"brand-{matched_class}"
            g["printer_model"] = p_data
        else:
            g["printer_model"] = None

    return templates.TemplateResponse(
        "guide.html",
        {
            "request": request,
            "guides": guides,  # ĐÃ SỬA: Đổi từ "guide" thành "guides" để khớp 100% với vòng lặp trong HTML
            "printers": printers,
            "search": search or "",
            "selected_printer_id":
                int(printer_model_id)
                if printer_model_id and printer_model_id.isdigit()
                else None,
            "status": guide_status
        }
    )



# =====================================================
# CREATE FORM
# =====================================================

@router.get(
    "/create",
    response_class=HTMLResponse
)
async def create_form(request: Request):

    printers = (
        supabase
        .table("printer_model")
        .select(
            "id, brand, model"
        )
        .order("brand")
        .execute()
        .data
        or []
    )


    return templates.TemplateResponse(
        "guide_create.html",
        {
            "request": request,
            "printers": printers
        }
    )



# =====================================================
# CREATE
# =====================================================

@router.post("/create")
async def create_submit(
    title: str = Form(...),
    printer_model_id: int = Form(...),
    description: Optional[str] = Form(""),
    is_active: Optional[str] = Form(None),
    sort_order: Optional[str] = Form("1"),
    image: Optional[UploadFile] = File(None)
):



    try:
        sort = int(sort_order)

    except:
        sort = 1



    data = {

        "title": title,

        "printer_model_id":
            printer_model_id,

        "description":
            description or "",

        "is_active":
            is_active in [
                "true",
                "on",
                "1"
            ],

        "sort_order":
            sort,

    
    }



    supabase.table(
        "guide"
    ).insert(
        data
    ).execute()



    return RedirectResponse(
        "/admin/guide",
        status_code=status.HTTP_303_SEE_OTHER
    )



# =====================================================
# EDIT FORM
# =====================================================

@router.get(
    "/edit/{guide_id}",
    response_class=HTMLResponse
)
async def edit_form(
    request: Request,
    guide_id: int
):

    guide_res = (
        supabase
        .table("guide")
        .select("*")
        .eq("id", guide_id)
        .execute()
    )


    if not guide_res.data:
        return RedirectResponse(
            "/admin/guide"
        )


    printers = (
        supabase
        .table("printer_model")
        .select(
            "id, brand, model"
        )
        .execute()
        .data
        or []
    )


    return templates.TemplateResponse(
        "guide_edit.html",
        {
            "request": request,
            "guide": guide_res.data[0],
            "printers": printers
        }
    )



# =====================================================
# EDIT
# =====================================================

@router.post("/edit/{guide_id}")
async def edit_submit(
    guide_id: int,

    title: str = Form(...),

    printer_model_id: int = Form(...),

    description: Optional[str] = Form(""),

    is_active: Optional[str] = Form(None),

    sort_order: Optional[str] = Form("1"),

    image: Optional[UploadFile] = File(None)
):


    update = {

        "title": title,

        "printer_model_id":
            printer_model_id,

        "description":
            description or "",

        "is_active":
            is_active in [
                "true",
                "on",
                "1"
            ],

        "sort_order":
            int(sort_order)
            if sort_order.isdigit()
            else 1

    }



    supabase.table(
        "guide"
    ).update(
        update
    ).eq(
        "id",
        guide_id
    ).execute()



    return RedirectResponse(
        "/admin/guide",
        status_code=status.HTTP_303_SEE_OTHER
    )



# =====================================================
# DELETE
# =====================================================

@router.post(
    "/delete/{guide_id}"
)
async def delete_guide(
    guide_id:int
):


    supabase.table(
        "guide"
    ).delete().eq(
        "id",
        guide_id
    ).execute()



    return RedirectResponse(
        "/admin/guide",
        status_code=status.HTTP_303_SEE_OTHER
    )



# =====================================================
# DETAIL
# =====================================================

@router.get(
    "/{guide_id}",
    response_class=HTMLResponse
)
async def view_guide(
    request: Request,
    guide_id:int
):

    res = (
        supabase
        .table("guide")
        .select("*")
        .eq("id", guide_id)
        .execute()
    )


    if not res.data:
        return RedirectResponse(
            "/admin/guide"
        )


    guide = res.data[0]


    printer = (
        supabase
        .table("printer_model")
        .select(
            "brand,model"
        )
        .eq(
            "id",
            guide["printer_model_id"]
        )
        .execute()
    )


    if printer.data:

        p = printer.data[0]

        guide["printer_name"] = (
            f"{p['brand']} {p['model']}"
        )

    else:

        guide["printer_name"] = "Không rõ máy"



    return templates.TemplateResponse(
        "guide_detail.html",
        {
            "request":request,
            "guide":guide
        }
    )