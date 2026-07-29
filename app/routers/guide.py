import os
import uuid
import re
from typing import Optional, List
from fastapi import APIRouter, Request, Form, UploadFile, File, status, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.routers.auth import require_admin
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
# AUTO-TAGGING HELPER FUNCTION
# =====================================================

async def auto_generate_and_link_tags(guide_id: int, printer_model_id: int, title: str):
    """
    Tự động phân tích Model máy in và Tiêu đề bài viết để sinh thẻ tag, 
    sau đó liên kết vào bảng guide_tags.
    """
    tag_names_to_add = set()

    # 1. Lấy thông tin Hãng và Model từ bảng printer_model
    printer_res = supabase.table("printer_model").select("brand, model").eq("id", printer_model_id).execute()
    if printer_res.data:
        p = printer_res.data[0]
        brand = p.get("brand", "").strip()
        model = p.get("model", "").strip()
        
        if brand:
            tag_names_to_add.add(brand)
        if model:
            tag_names_to_add.add(model)
        if brand and model:
            tag_names_to_add.add(f"{brand} {model}")

    # 2. Bóc tách các từ khóa/cụm từ có ý nghĩa kỹ thuật từ tiêu đề (title)
    if title:
        # Chuẩn hóa tiêu đề, loại bỏ các ký tự đặc biệt thừa nhưng giữ lại chữ cái, số, tiếng Việt
        clean_title = re.sub(r'[^\w\sàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]', ' ', title.lower())
        
        # Danh sách các từ dừng (stop words) thông thường cần lọc bỏ để tránh tạo các tag vô nghĩa
        stop_words = {
            'cách', 'hướng', 'dẫn', 'làm', 'sao', 'để', 'và', 'của', 'cho', 'trong', 
            'ngoài', 'khi', 'bị', 'lỗi', 'trên', 'dưới', 'với', 'từ', 'đến', 'này', 
            'kia', 'các', 'những', 'một', 'có', 'không', 'được', 'bằng', 'về', 'thế'
        }
        
        words = clean_title.split()
        
        # Thêm các từ đơn có ý nghĩa kỹ thuật (>= 3 ký tự và không nằm trong stop_words)
        for w in words:
            if len(w) >= 3 and w not in stop_words:
                tag_names_to_add.add(w.capitalize())

        # Tạo thêm các cụm từ đôi liên tiếp (ví dụ: "kẹt giấy", "reset mực", "lỗi đầu") để làm tag phong phú hơn
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i+1]
            if w1 not in stop_words and w2 not in stop_words:
                phrase = f"{w1} {w2}"
                if len(phrase) >= 5:
                    tag_names_to_add.add(phrase.capitalize())

    # 3. Đồng bộ danh sách tag vào Database (bảng tags và guide_tags)
    tag_ids = []
    for name in tag_names_to_add:
        # Kiểm tra xem tag đã tồn tại chưa
        existing = supabase.table("tags").select("id").eq("name", name).execute()
        
        if existing.data:
            tag_id = existing.data[0]["id"]
        else:
            # Nếu chưa có, tự động tạo mới tag với màu mặc định
            new_tag = supabase.table("tags").insert({"name": name, "color": "blue"}).execute()
            if new_tag.data:
                tag_id = new_tag.data[0]["id"]
            else:
                continue
        tag_ids.append(tag_id)

    # 4. Xóa liên kết tag cũ (nếu là cập nhật) và thêm mới liên kết vào guide_tags
    supabase.table("guide_tags").delete().eq("guide_id", guide_id).execute()
    
    if tag_ids:
        tag_links = [{"guide_id": guide_id, "tag_id": tid} for tid in tag_ids]
        try:
            supabase.table("guide_tags").insert(tag_links).execute()
        except Exception:
            pass


# =====================================================
# LIST (Cập nhật lấy danh sách Tags & Lọc theo Tag)
# =====================================================

@router.get("/", response_class=HTMLResponse)
async def list_guides(
    request: Request,
    search: Optional[str] = None,
    printer_model_id: Optional[str] = None,
    guide_status: Optional[str] = None,
    tag_id: Optional[int] = None # <--- Bổ sung nhận tham số lọc theo tag
):
    query = (
        supabase
        .table("guide")
        .select("*, guide_tags(tag_id, tags(*))") # Lấy kèm thông tin bảng quan hệ tags
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

    # Nếu có lọc theo tag_id trên giao diện, lọc trực tiếp trên danh sách kết quả hoặc qua query Supabase
    if tag_id:
        guides = [
            g for g in guides 
            if any(gt.get("tag_id") == tag_id for gt in g.get("guide_tags", []))
        ]

    # Lấy toàn bộ danh sách tags để hiển thị bộ lọc trên giao diện
    tags_res = supabase.table("tags").select("*").order("name").execute()
    all_tags = tags_res.data or []

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

    known_brands = ["brother", "canon", "epson", "hp"]

    for g in guides:
        p_id = g.get("printer_model_id")
        p = printer_map.get(p_id)
        
        if p:
            p_data = p.copy()
            brand_lower = p_data.get("brand", "").strip().lower()
            
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
            "guides": guides,
            "printers": printers,
            "all_tags": all_tags, # Truyền danh sách tag ra template
            "selected_tag_id": tag_id, # Truyền tag đang chọn
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
# CREATE (Tự động sinh và lưu Tag)
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
        "printer_model_id": printer_model_id,
        "description": description or "",
        "is_active": is_active in ["true", "on", "1"],
        "sort_order": sort,
    }

    # 1. Thêm hướng dẫn và lấy ID vừa tạo
    res = supabase.table("guide").insert(data).execute()
    
    if res.data:
        new_guide_id = res.data[0]["id"]
        
        # 2. Tự động sinh và gắn thẻ tag dựa vào model máy và tiêu đề bài viết
        await auto_generate_and_link_tags(new_guide_id, printer_model_id, title)

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
# EDIT (Cập nhật thông tin và tái tạo lại Tag tự động)
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
        "printer_model_id": printer_model_id,
        "description": description or "",
        "is_active": is_active in ["true", "on", "1"],
        "sort_order": int(sort_order) if sort_order.isdigit() else 1
    }

    # 1. Cập nhật bảng guide chính
    supabase.table("guide").update(update).eq("id", guide_id).execute()

    # 2. Tự động cập nhật và sinh lại danh sách Tag theo tiêu đề/model mới chỉnh sửa
    await auto_generate_and_link_tags(guide_id, printer_model_id, title)

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
    guide_id: int
):
    # Do cấu hình bảng database có ON DELETE CASCADE nên khi xóa guide, bảng guide_tags sẽ tự động xóa theo
    supabase.table("guide").delete().eq("id", guide_id).execute()

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
    guide_id: int
):
    res = (
        supabase
        .table("guide")
        .select("*, guide_tags(tag_id, tags(*))") # Lấy kèm thông tin tag khi xem chi tiết bài viết
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
            "brand, model"
        )
        .eq(
            "id",
            guide["printer_model_id"]
        )
        .execute()
    )

    if printer.data:
        p = printer.data[0]
        guide["printer_name"] = f"{p['brand']} {p['model']}"
    else:
        guide["printer_name"] = "Không rõ máy"

    return templates.TemplateResponse(
        "guide_detail.html",
        {
            "request": request,
            "guide": guide
        }
    )