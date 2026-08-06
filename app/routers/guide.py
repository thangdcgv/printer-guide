
import re
import math
import logging
from typing import Optional

from fastapi import APIRouter, Request, Form, status, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.routers.auth import require_admin
from app.database import supabase

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/guide",
    tags=["guide"],
    dependencies=[Depends(require_admin)]  # Khóa toàn bộ các route quản lý bài viết
)

templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/images"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
KNOWN_BRANDS = ["brother", "canon", "epson", "hp"]
STOP_WORDS = {
    'cách', 'hướng', 'dẫn', 'làm', 'sao', 'để', 'và', 'của', 'cho', 'trong', 
    'ngoài', 'khi', 'bị', 'lỗi', 'trên', 'dưới', 'với', 'từ', 'đến', 'này', 
    'kia', 'các', 'những', 'một', 'có', 'không', 'được', 'bằng', 'về', 'thế'
}


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def _get_brand_class(brand_name: str) -> str:
    """Xác định class CSS hiển thị theo hãng máy in."""
    brand_lower = (brand_name or "").strip().lower()
    for kb in KNOWN_BRANDS:
        if kb in brand_lower:
            return f"brand-{kb}"
    return "brand-other"


async def auto_generate_and_link_tags(guide_id: int, printer_model_id: int, title: str) -> None:
    """
    Tự động phân tích Model máy in và Tiêu đề bài viết để sinh thẻ tag, 
    sau đó liên kết vào bảng guide_tags (Tối ưu hóa Batch Query).
    """
    tag_names_to_add = set()

    # 1. Lấy thông tin Hãng và Model từ bảng printer_model
    try:
        printer_res = supabase.table("printer_model").select("brand, model").eq("id", printer_model_id).execute()
        if printer_res.data:
            p = printer_res.data[0]
            brand = (p.get("brand") or "").strip()
            model = (p.get("model") or "").strip()
            
            if brand:
                tag_names_to_add.add(brand)
            if model:
                tag_names_to_add.add(model)
            if brand and model:
                tag_names_to_add.add(f"{brand} {model}")
    except Exception as e:
        logger.error(f"Lỗi khi lấy printer_model #{printer_model_id}: {e}")

    # 2. Bóc tách các từ khóa từ tiêu đề (title)
    if title:
        clean_title = re.sub(
            r'[^\w\sàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]',
            ' ',
            title.lower()
        )
        words = clean_title.split()
        
        # Từ đơn
        for w in words:
            if len(w) >= 3 and w not in STOP_WORDS:
                tag_names_to_add.add(w.capitalize())

        # Cụm từ đôi
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if w1 not in STOP_WORDS and w2 not in STOP_WORDS:
                phrase = f"{w1} {w2}"
                if len(phrase) >= 5:
                    tag_names_to_add.add(phrase.capitalize())

    if not tag_names_to_add:
        supabase.table("guide_tags").delete().eq("guide_id", guide_id).execute()
        return

    # 3. Batch Query & Insert đồng bộ Tags vào Database (Tránh N+1 query)
    try:
        tag_names_list = list(tag_names_to_add)
        
        # Tìm danh sách tag đã tồn tại
        existing_tags_res = supabase.table("tags").select("id, name").in_("name", tag_names_list).execute()
        existing_tags = existing_tags_res.data or []
        
        tag_map = {t["name"]: t["id"] for t in existing_tags}
        
        # Tạo mới các tag chưa có
        missing_names = [name for name in tag_names_list if name not in tag_map]
        if missing_names:
            new_tags_payload = [{"name": name, "color": "blue"} for name in missing_names]
            new_tags_res = supabase.table("tags").insert(new_tags_payload).execute()
            if new_tags_res.data:
                for t in new_tags_res.data:
                    tag_map[t["name"]] = t["id"]

        tag_ids = list(tag_map.values())

        # 4. Làm sạch liên kết cũ và thêm mới vào guide_tags
        supabase.table("guide_tags").delete().eq("guide_id", guide_id).execute()
        if tag_ids:
            tag_links = [{"guide_id": guide_id, "tag_id": tid} for tid in tag_ids]
            supabase.table("guide_tags").insert(tag_links).execute()

    except Exception as e:
        logger.error(f"Lỗi khi đồng bộ tags cho guide #{guide_id}: {e}")


# =====================================================
# LIST
# =====================================================

@router.get("/", response_class=HTMLResponse)
async def list_guides(
    request: Request,
    search: Optional[str] = None,
    printer_model_id: Optional[str] = None,
    guide_status: Optional[str] = None,
    tag_id: Optional[str] = None,  # 🟢 ĐÃ SỬA: Đổi từ Optional[int] sang Optional[str]
    page: int = 1,
    current_user: dict = Depends(require_admin)
):
    PER_PAGE = 10
    page = max(1, page)
    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE - 1

    # 🟢 Ép kiểu an toàn cho tag_id
    parsed_tag_id = int(tag_id) if tag_id and tag_id.isdigit() else None

    def build_query(select_fields: str):
        query = supabase.table("guide").select(select_fields, count="exact")
        if search and search.strip():
            query = query.ilike("title", f"%{search.strip()}%")
        if printer_model_id and printer_model_id.isdigit():
            query = query.eq("printer_model_id", int(printer_model_id))
        if guide_status in ["0", "1"]:
            query = query.eq("is_active", guide_status == "1")
        if parsed_tag_id:
            query = query.eq("guide_tags.tag_id", parsed_tag_id)
        return query.order("sort_order").order("id", desc=True)

    try:
        tag_relation = "guide_tags!inner(tag_id, tags(*))" if parsed_tag_id else "guide_tags(tag_id, tags(*))"
        select_query = f"*, {tag_relation}, quan_tri_vien!created_by(ho_ten, username)"
        
        guides_res = build_query(select_query).range(start_idx, end_idx).execute()
        guides = guides_res.data or []
        total_count = guides_res.count or 0
    except Exception as e:
        logger.warning(f"Lỗi query phân trang, fallback về query thường: {e}")
        guides_res = build_query("*").range(start_idx, end_idx).execute()
        guides = guides_res.data or []
        total_count = guides_res.count or 0

    total_pages = math.ceil(total_count / PER_PAGE) if total_count > 0 else 1

    # Lấy danh sách tags
    try:
        tags_res = supabase.table("tags").select("*").order("name").execute()
        all_tags = tags_res.data or []
    except Exception as e:
        logger.warning(f"Chưa thể lấy danh sách tags: {e}")
        all_tags = []

    # Lấy danh sách printer models
    printers_res = (
        supabase
        .table("printer_model")
        .select("id, brand, model")
        .order("brand")
        .order("model")
        .execute()
    )
    printers = printers_res.data or []
    printer_map = {p["id"]: p for p in printers}

    for g in guides:
        p = printer_map.get(g.get("printer_model_id"))
        if p:
            p_data = p.copy()
            p_data["brand_class"] = _get_brand_class(p_data.get("brand", ""))
            g["printer_model"] = p_data
        else:
            g["printer_model"] = None

    return templates.TemplateResponse(
        "guide.html",
        {
            "request": request,
            "user": current_user,
            "guides": guides,
            "printers": printers,
            "all_tags": all_tags,
            "selected_tag_id": parsed_tag_id,
            "search": search or "",
            "selected_printer_id": int(printer_model_id) if printer_model_id and printer_model_id.isdigit() else None,
            "status": guide_status,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "per_page": PER_PAGE
        }
    )


# =====================================================
# CREATE
# =====================================================

@router.get("/create", response_class=HTMLResponse)
async def create_form(
    request: Request,
    current_user: dict = Depends(require_admin)
):
    printers = (
        supabase
        .table("printer_model")
        .select("id, brand, model")
        .order("brand")
        .execute()
        .data or []
    )

    return templates.TemplateResponse(
        "guide_create.html",
        {
            "request": request,
            "user": current_user,  # 👈 Bổ sung user
            "printers": printers
        }
    )


@router.post("/create")
async def create_submit(
    title: str = Form(...),
    printer_model_id: int = Form(...),
    description: Optional[str] = Form(""),
    image_url: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    sort_order: Optional[str] = Form("1"),
    current_user: dict = Depends(require_admin)
):
    try:
        sort = int(sort_order) if sort_order and sort_order.isdigit() else 1
    except ValueError:
        sort = 1

    clean_image_url = image_url.strip() if image_url and image_url.strip() else None
    clean_video_url = video_url.strip() if video_url and video_url.strip() else None  # 🟢 CHUẨN HÓA LINK VIDEO
    # Lấy ID của quản trị viên từ bảng quan_tri_vien dựa vào email trong current_user
    admin_id = None
    try:
        user_email = current_user.get("email")
        if user_email:
            admin_res = supabase.table("quan_tri_vien").select("id").eq("email", user_email).execute()
            if admin_res.data:
                admin_id = admin_res.data[0]["id"]
    except Exception as e:
        logger.error(f"Không thể lấy id quản trị viên: {e}")

    data = {
        "title": title.strip(),
        "printer_model_id": printer_model_id,
        "description": description.strip() if description else "",
        "image_url": clean_image_url,
        "video_url": clean_video_url,  # 🟢 LƯU VIDEO_URL VÀO DATABASE
        "is_active": is_active in ["true", "on", "1"],
        "sort_order": sort,
        "created_by": admin_id
    }

    try:
        res = supabase.table("guide").insert(data).execute()
        if res.data:
            new_guide_id = res.data[0]["id"]
            await auto_generate_and_link_tags(new_guide_id, printer_model_id, title.strip())
    except Exception as e:
        logger.error(f"Lỗi khi tạo mới bài hướng dẫn: {e}")

    return RedirectResponse(
        "/admin/guide",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/copy/{guide_id}")
async def copy_guide(
    guide_id: int,
    current_user: dict = Depends(require_admin)  # 🟢 ĐÃ SỬA: Lấy user hiện tại khi copy
):
    try:
        # Lấy ID của admin thực hiện sao chép
        admin_id = None
        try:
            user_email = current_user.get("email")
            if user_email:
                admin_res = supabase.table("quan_tri_vien").select("id").eq("email", user_email).execute()
                if admin_res.data:
                    admin_id = admin_res.data[0]["id"]
        except Exception as e:
            logger.error(f"Không thể lấy id quản trị viên khi sao chép bài: {e}")

        # 1. Lấy thông tin bài viết gốc
        guide_res = supabase.table("guide").select("*").eq("id", guide_id).execute()
        
        if not guide_res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy bài viết hướng dẫn gốc!")
        
        original_guide = guide_res.data[0]
        
        # 2. Chuẩn bị dữ liệu bài viết mới
        new_guide_data = {
            "printer_model_id": original_guide.get("printer_model_id"),
            "title": f"{original_guide['title']} (Bản sao)",
            "description": original_guide.get("description"),
            "image_url": original_guide.get("image_url"),
            "video_url": original_guide.get("video_url"),  # 🟢 SAO CHÉP LUÔN VIDEO_URL
            "sort_order": (original_guide.get("sort_order") or 1) + 1,
            "is_active": False,
            "created_by": admin_id  # 🟢 ĐÃ SỬA: Gán người tạo bài sao chép
        }
        
        # 3. Thêm bản ghi mới
        insert_guide_res = supabase.table("guide").insert(new_guide_data).execute()
        if not insert_guide_res.data:
            raise HTTPException(status_code=500, detail="Không thể tạo bản sao bài viết trong cơ sở dữ liệu.")
            
        new_guide = insert_guide_res.data[0]
        new_guide_id = new_guide["id"]
        
        # 4. Sao chép toàn bộ các bước hướng dẫn (guide_step)
        steps_res = supabase.table("guide_step").select("*").eq("guide_id", guide_id).execute()
        if steps_res.data:
            new_steps_list = []
            for step in steps_res.data:
                new_steps_list.append({
                    "guide_id": new_guide_id,
                    "step_number": step.get("step_number"),
                    "title": step.get("title"),
                    "content": step.get("content"),
                    "note": step.get("note"),
                    "video_url": step.get("video_url"),
                    "download_url": step.get("download_url"),
                    "image_urls": step.get("image_urls"),
                    "is_active": step.get("is_active", True)
                })
            
            if new_steps_list:
                supabase.table("guide_step").insert(new_steps_list).execute()
        
        # 5. Đồng bộ tags cho bài viết mới
        if new_guide_data["printer_model_id"]:
            await auto_generate_and_link_tags(new_guide_id, new_guide_data["printer_model_id"], new_guide_data["title"])

        return {
            "success": True,
            "message": "Sao chép bài viết thành công!",
            "new_guide_id": new_guide_id
        }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống khi sao chép bài viết: {str(e)}")
# =====================================================
# EDIT
# =====================================================

@router.get("/edit/{guide_id}", response_class=HTMLResponse)
async def edit_form(
    request: Request, 
    guide_id: int,
    current_user: dict = Depends(require_admin)
):
    guide_res = (
        supabase
        .table("guide")
        .select("*")
        .eq("id", guide_id)
        .execute()
    )

    if not guide_res.data:
        return RedirectResponse("/admin/guide")

    printers = (
        supabase
        .table("printer_model")
        .select("id, brand, model")
        .execute()
        .data or []
    )

    return templates.TemplateResponse(
        "guide_edit.html",
        {
            "request": request,
            "user": current_user,  # 👈 Bổ sung user
            "guide": guide_res.data[0],
            "printers": printers
        }
    )


@router.post("/edit/{guide_id}")
async def edit_submit(
    guide_id: int,
    title: str = Form(...),
    printer_model_id: int = Form(...),
    description: Optional[str] = Form(""),
    image_url: Optional[str] = Form(None),
    video_url: Optional[str] = Form(None),  # 🟢 THÊM PARAMETER NÀY
    is_active: Optional[str] = Form(None),
    sort_order: Optional[str] = Form("1")
):
    clean_image_url = image_url.strip() if image_url and image_url.strip() else None
    clean_video_url = video_url.strip() if video_url and video_url.strip() else None  # 🟢 CHUẨN HÓA LINK VIDEO

    update = {
        "title": title.strip(),
        "printer_model_id": printer_model_id,
        "description": description.strip() if description else "",
        "image_url": clean_image_url,
        "video_url": clean_video_url,  # 🟢 CẬP NHẬT VIDEO_URL VÀO DATABASE
        "is_active": is_active in ["true", "on", "1"],
        "sort_order": int(sort_order) if sort_order and sort_order.isdigit() else 1
    }

    try:
        supabase.table("guide").update(update).eq("id", guide_id).execute()
        await auto_generate_and_link_tags(guide_id, printer_model_id, title.strip())
    except Exception as e:
        logger.error(f"Lỗi khi cập nhật bài hướng dẫn #{guide_id}: {e}")

    return RedirectResponse("/admin/guide", status_code=status.HTTP_303_SEE_OTHER)


# =====================================================
# DELETE
# =====================================================

@router.post("/delete/{guide_id}")
async def delete_guide(guide_id: int):
    try:
        supabase.table("guide").delete().eq("id", guide_id).execute()
    except Exception as e:
        logger.error(f"Lỗi khi xóa bài hướng dẫn #{guide_id}: {e}")
        
    return RedirectResponse("/admin/guide", status_code=status.HTTP_303_SEE_OTHER)


# =====================================================
# DETAIL
# =====================================================

@router.get("/{guide_id}", response_class=HTMLResponse)
async def view_guide(
    request: Request, 
    guide_id: int,
    current_user: dict = Depends(require_admin)
):
    res = (
        supabase
        .table("guide")
        .select("*, guide_tags(tag_id, tags(*)), quan_tri_vien!created_by(ho_ten, username)")  # 🟢 ĐÃ SỬA: Kéo thêm quan_tri_vien
        .eq("id", guide_id)
        .execute()
    )

    if not res.data:
        return RedirectResponse("/admin/guide")

    guide = res.data[0]

    printer = (
        supabase
        .table("printer_model")
        .select("brand, model")
        .eq("id", guide["printer_model_id"])
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
            "user": current_user,
            "guide": guide
        }
    )
