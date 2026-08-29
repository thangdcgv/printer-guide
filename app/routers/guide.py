import re
import math
import logging
from typing import Optional

from app.services.storage_service import upload_image_to_supabase, delete_image_from_supabase
from fastapi import APIRouter, Request, Form, status, HTTPException, Depends, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.routers.auth import require_login
from app.database import supabase

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/guide",
    tags=["guide"],
    dependencies=[Depends(require_login)]  # Khóa toàn bộ các route quản lý bài viết
)

templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = "app/static/images"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
KNOWN_BRANDS = ["brother", "canon", "epson", "hp"]
# Từ khóa kỹ thuật ngành máy in cố định (Whitelist)
TECHNICAL_KEYWORDS = [
    "Driver", "Reset", "Mã lỗi", "Hộp bảo trì", "Đầu phun", 
    "Kẹt giấy", "Bơm mực", "Nạp mực", "Firmware", "Cài đặt", 
    "Sửa lỗi", "Tháo lắp", "Cáp in", "Mainboard", "Lắp mực", 
    "Mực in", "In qua Wifi", "In mạng", "Cổng USB"
]


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

async def auto_generate_and_link_tags(guide_id: int, printer_model_id: Optional[int], title: str) -> None:
    """
    Tự động sinh tag CHUẨN XÁC từ Model máy in và Danh mục từ khóa Kỹ thuật định sẵn.
    """
    tag_names_to_add = set()

    # 1. Lấy Hãng và Model từ bảng printer_model (Rất chuẩn xác)
    if printer_model_id:
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

    # 2. Quét tiêu đề theo Whitelist từ khóa Kỹ thuật (Tránh sinh từ rác)
    if title:
        title_lower = title.lower()
        for kw in TECHNICAL_KEYWORDS:
            # Kiểm tra xem từ khóa kỹ thuật có xuất hiện trong tiêu đề không
            if re.search(r'\b' + re.escape(kw.lower()) + r'\b', title_lower):
                tag_names_to_add.add(kw)

    # Nếu không có tag nào phù hợp -> Xóa link cũ và thoát
    if not tag_names_to_add:
        supabase.table("guide_tags").delete().eq("guide_id", guide_id).execute()
        return

    # 3. Đồng bộ với Database (Xử lý Case-insensitive để tránh trùng tag)
    try:
        tag_names_list = list(tag_names_to_add)
        
        # Lấy toàn bộ tag hiện có để map chính xác ID
        existing_tags_res = supabase.table("tags").select("id, name").execute()
        all_existing_tags = existing_tags_res.data or []
        
        # Map tên tag (lowercase) -> ID
        existing_map = {t["name"].strip().lower(): t["id"] for t in all_existing_tags}
        
        tag_ids = []
        missing_payload = []

        for name in tag_names_list:
            clean_name_lower = name.strip().lower()
            if clean_name_lower in existing_map:
                tag_ids.append(existing_map[clean_name_lower])
            else:
                # Chỉ tạo mới nếu là Hãng/Model hoặc Từ khóa kỹ thuật hợp lệ
                missing_payload.append({"name": name, "color": "blue"})

        # Thêm các tag mới chưa có trong DB
        if missing_payload:
            new_tags_res = supabase.table("tags").insert(missing_payload).execute()
            if new_tags_res.data:
                for nt in new_tags_res.data:
                    tag_ids.append(nt["id"])

        # 4. Cập nhật lại liên kết trong guide_tags
        supabase.table("guide_tags").delete().eq("guide_id", guide_id).execute()
        if tag_ids:
            # Loại bỏ ID trùng lặp nếu có
            unique_tag_ids = list(set(tag_ids))
            tag_links = [{"guide_id": guide_id, "tag_id": tid} for tid in unique_tag_ids]
            supabase.table("guide_tags").insert(tag_links).execute()

    except Exception as e:
        logger.error(f"Lỗi khi đồng bộ tags cho guide #{guide_id}: {e}")
#Helpẻr check quyền xóa sửa
def _check_guide_permission(guide_id: int, current_user: dict) -> dict:
    """
    Kiểm tra quyền hạn tác động lên bài viết:
    - Trả về dict thông tin bài viết nếu hợp lệ.
    - Chặn và bắn HTTPException 403 nếu không có quyền.
    """
    # 1. Truy vấn bài viết để lấy created_by
    res = supabase.table("guide").select("id, title, created_by").eq("id", guide_id).execute()
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Bài viết không tồn tại trên hệ thống."
        )
    
    guide = res.data[0]
    
    # 2. Quyền 1: Nếu là Admin -> Cho phép toàn quyền
    user_role = current_user.get("role")
    if user_role in ("Admin","Super Admin","System Admin"):
        return guide

    # 3. Quyền 2: Nếu là người tạo ra bài viết (created_by trùng id người dùng) -> Cho phép
    user_id = current_user.get("id")
    if guide.get("created_by") is not None and guide.get("created_by") == user_id:
        return guide

    # 4. Trường hợp còn lại -> Chặn truy cập
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="⛔ Bạn không có quyền chỉnh sửa hoặc xóa bài viết này!"
    )
# =====================================================
# HELPER FUNCTIONS (Cập nhật _get_admin_id)
# =====================================================

def _get_admin_id(current_user: dict) -> Optional[int]:
    """Helper lấy ID (integer) của quản trị viên từ thông tin session/user."""
    if not current_user or not isinstance(current_user, dict):
        logger.warning("❌ [DEBUG _get_admin_id]: current_user bị rỗng hoặc không phải dict!")
        return None
    
    print(f"\n👉 [DEBUG _get_admin_id] RAW USER SESSION: {current_user}", flush=True)

    # 1. Kiểm tra nếu trong session đã lưu sẵn ID nguyên bản (integer của bảng quan_tri_vien)
    for key in ["id", "admin_id", "quan_tri_vien_id"]:
        val = current_user.get(key)
        if val is not None and str(val).isdigit():
            admin_id = int(val)
            print(f"✅ [DEBUG _get_admin_id]: Tìm thấy ID trực tiếp = {admin_id}", flush=True)
            return admin_id

    # 2. Tra cứu bằng auth_id (Supabase Auth UUID)
    # Thường session lưu UUID ở key 'user_id', 'auth_id', hoặc 'sub'
    possible_auth_ids = [
        current_user.get("auth_id"),
        current_user.get("user_id"),
        current_user.get("sub")
    ]
    
    for auth_id in possible_auth_ids:
        if auth_id and isinstance(auth_id, str):
            try:
                res = supabase.table("quan_tri_vien").select("id").eq("auth_id", auth_id).execute()
                if res.data and len(res.data) > 0:
                    admin_id = res.data[0]["id"]
                    print(f"✅ [DEBUG _get_admin_id]: Tìm thấy ID qua auth_id ({auth_id}) = {admin_id}", flush=True)
                    return admin_id
            except Exception as e:
                logger.error(f"Lỗi tra cứu quan_tri_vien theo auth_id ({auth_id}): {e}")

    # 3. Tra cứu qua email
    user_email = current_user.get("email")
    if user_email:
        try:
            res = supabase.table("quan_tri_vien").select("id").eq("email", user_email).execute()
            if res.data and len(res.data) > 0:
                admin_id = res.data[0]["id"]
                print(f"✅ [DEBUG _get_admin_id]: Tìm thấy ID qua email ({user_email}) = {admin_id}", flush=True)
                return admin_id
        except Exception as e:
            logger.error(f"Lỗi tra cứu quan_tri_vien theo email ({user_email}): {e}")

    # 4. Tra cứu qua username
    username = current_user.get("username")
    if username:
        try:
            res = supabase.table("quan_tri_vien").select("id").eq("username", username).execute()
            if res.data and len(res.data) > 0:
                admin_id = res.data[0]["id"]
                print(f"✅ [DEBUG _get_admin_id]: Tìm thấy ID qua username ({username}) = {admin_id}", flush=True)
                return admin_id
        except Exception as e:
            logger.error(f"Lỗi tra cứu quan_tri_vien theo username ({username}): {e}")

    print("❌ [DEBUG _get_admin_id]: Không thể xác định được ID quản trị viên!", flush=True)
    return None

# =====================================================
# LIST (Cập nhật list_guides với Dual Fallback Map)
# =====================================================

@router.get("/", response_class=HTMLResponse)
async def list_guides(
    request: Request,
    search: Optional[str] = None,
    printer_model_id: Optional[str] = None,
    created_by: Optional[str] = None,  # 1. Đã bổ sung nhận tham số created_by từ URL/Form
    author_id: Optional[str] = None,   # Giữ lại author_id để hỗ trợ tương thích ngược
    guide_status: Optional[str] = None,
    tag_id: Optional[str] = None,
    page: int = 1,
    current_user: dict = Depends(require_login)
):
    PER_PAGE = 10
    page = max(1, page)

    # Lấy ID tác giả từ created_by (ưu tiên) hoặc author_id
    raw_author_id = created_by or author_id

    parsed_tag_id = int(tag_id) if tag_id and tag_id.isdigit() else None
    parsed_author_id = int(raw_author_id) if raw_author_id and raw_author_id.isdigit() else None

    def build_query(select_fields: str):
        query = supabase.table("guide").select(select_fields, count="exact")
        if search and search.strip():
            query = query.ilike("title", f"%{search.strip()}%")
        if printer_model_id and printer_model_id.isdigit():
            query = query.eq("printer_model_id", int(printer_model_id))
        if parsed_author_id:  # Lọc theo created_by
            query = query.eq("created_by", parsed_author_id)
        if guide_status in ["0", "1"]:
            query = query.eq("is_active", guide_status == "1")
        if parsed_tag_id:
            query = query.eq("guide_tags.tag_id", parsed_tag_id)
            
        return query.order("is_pinned", desc=True).order("sort_order").order("id", desc=True)

    # 1. Truy vấn bài viết từ Supabase
    tag_relation = "guide_tags!inner(tag_id, tags(*))" if parsed_tag_id else "guide_tags(tag_id, tags(*))"
    select_query = f"*, printer_model(*), {tag_relation}, quan_tri_vien!created_by(ho_ten, username)"

    try:
        start_idx = (page - 1) * PER_PAGE
        end_idx = start_idx + PER_PAGE - 1
        guides_res = build_query(select_query).range(start_idx, end_idx).execute()
        guides = guides_res.data or []
        total_count = guides_res.count if guides_res.count is not None else len(guides)
        
    except Exception as e:
        logger.warning(f"Lỗi query JOIN nâng cao, chuyển sang fallback query cơ bản: {e}")
        try:
            fallback_select = f"*, {tag_relation}" if parsed_tag_id else "*"
            start_idx = (page - 1) * PER_PAGE
            end_idx = start_idx + PER_PAGE - 1
            guides_res = build_query(fallback_select).range(start_idx, end_idx).execute()
            guides = guides_res.data or []
            total_count = guides_res.count if guides_res.count is not None else len(guides)
        except Exception as fb_err:
            logger.error(f"Fallback query cũng thất bại: {fb_err}")
            guides = []
            total_count = 0

    # 2. Tính tổng số trang an toàn
    total_pages = (total_count + PER_PAGE - 1) // PER_PAGE if total_count > 0 else 1

    # 3. XỬ LÝ BẮT LỖI TỰ ĐỘNG RESET VỀ TRANG 1 KHI VƯỢT QUÁ SỐ TRANG BÀI VIẾT
    if page > total_pages and total_count > 0:
        page = 1
        start_idx = 0
        end_idx = PER_PAGE - 1
        try:
            guides_res = build_query(select_query).range(start_idx, end_idx).execute()
            guides = guides_res.data or []
        except Exception:
            fallback_select = f"*, {tag_relation}" if parsed_tag_id else "*"
            guides_res = build_query(fallback_select).range(start_idx, end_idx).execute()
            guides = guides_res.data or []

    # 4. Lấy danh sách tags
    try:
        tags_res = supabase.table("tags").select("*").order("name").execute()
        all_tags = tags_res.data or []
    except Exception as e:
        logger.warning(f"Chưa thể lấy danh sách tags: {e}")
        all_tags = []

    # 5. Lấy danh sách printer models tạo Map tra cứu
    try:
        printers_res = (
            supabase
            .table("printer_model")
            .select("id, brand, model")
            .order("brand")
            .order("model")
            .execute()
        )
        printers = printers_res.data or []
    except Exception as e:
        logger.warning(f"Không thể lấy danh sách printer_model: {e}")
        printers = []

    printer_map = {str(p["id"]): p for p in printers}

    # 6. Lấy danh sách quan_tri_vien có bài viết
    authors = []
    admin_map = {}
    try:
        guide_authors_res = (
            supabase
            .table("guide")
            .select("created_by")
            .not_.is_("created_by", "null")
            .execute()
        )
        active_author_ids = list({
            item["created_by"] 
            for item in (guide_authors_res.data or []) 
            if item.get("created_by") is not None
        })

        if active_author_ids:
            admins_res = (
                supabase
                .table("quan_tri_vien")
                .select("id, ho_ten, username")
                .in_("id", active_author_ids)
                .order("ho_ten")
                .execute()
            )
            authors = admins_res.data or []
            admin_map = {str(a["id"]): a for a in authors}
            
    except Exception as e:
        logger.warning(f"Không thể tải danh sách tác giả có bài viết: {e}")
        authors = []
        admin_map = {}

    # 7. Xử lý gán dữ liệu printer_model và quan_tri_vien an toàn
    for g in guides:
        if not g.get("printer_model") and g.get("printer_model_id") is not None:
            pm_key = str(g["printer_model_id"])
            if pm_key in printer_map:
                g["printer_model"] = printer_map[pm_key].copy()

        if g.get("printer_model") and isinstance(g["printer_model"], dict):
            brand_name = g["printer_model"].get("brand", "")
            g["printer_model"]["brand_class"] = _get_brand_class(brand_name) if "_get_brand_class" in globals() else brand_name.lower()

        if not g.get("quan_tri_vien") and g.get("created_by") is not None:
            admin_key = str(g["created_by"])
            if admin_key in admin_map:
                g["quan_tri_vien"] = admin_map[admin_key]

    selected_pm_id = int(printer_model_id) if printer_model_id and printer_model_id.isdigit() else None

    # 8. Truyền dữ liệu sang Template Jinja2 (Bổ sung selected_created_by)
    return templates.TemplateResponse(
        "guide.html",
        {
            "request": request,
            "user": current_user,
            "guides": guides,
            "printers": printers,
            "printer_models": printers,
            "authors": authors,
            "selected_created_by": raw_author_id or "",  # Truyền biến mới khớp với UI
            "selected_author_id": raw_author_id or "",   # Giữ biến cũ để không vỡ template cũ
            "all_tags": all_tags,
            "selected_tag_id": parsed_tag_id,
            "search": search or "",
            "search_query": search or "",
            "selected_printer_id": selected_pm_id,
            "selected_model": selected_pm_id,
            "status": guide_status,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "total_guides": total_count,
            "total_items": total_count,
            "per_page": PER_PAGE
        }
    )


# =====================================================
# PIN
# =====================================================

@router.post("/toggle-pin/{guide_id}")
async def toggle_pin_guide(
    guide_id: int,
    current_user: dict = Depends(require_login)
):
    try:
        res = supabase.table("guide").select("is_pinned").eq("id", guide_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")

        current_pinned = res.data[0].get("is_pinned") or False
        supabase.table("guide").update({"is_pinned": not current_pinned}).eq("id", guide_id).execute()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi cập nhật ghim bài viết #{guide_id}: {e}")
        raise HTTPException(status_code=500, detail="Không thể cập nhật trạng thái ghim")

    return RedirectResponse(url="/admin/guide", status_code=status.HTTP_303_SEE_OTHER)

# =====================================================
# CREATE
# =====================================================

@router.get("/create", response_class=HTMLResponse)
async def create_form(
    request: Request,
    current_user: dict = Depends(require_login)
):
    printers = (
        supabase
        .table("printer_model")
        .select("id, brand, model")
        .order("brand")
        .order("model")
        .execute()
        .data or []
    )

    return templates.TemplateResponse(
        "guide_create.html",
        {
            "request": request,
            "user": current_user,
            "printers": printers
        }
    )


@router.post("/create")
async def create_submit(
    title: str = Form(...),
    printer_model_id: int = Form(...),
    description: Optional[str] = Form(""),
    image_file: Optional[UploadFile] = File(None),  # 🆕 File ảnh upload từ máy
    image_url: Optional[str] = Form(None),          # Fallback URL nhập tay
    video_url: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    sort_order: Optional[str] = Form("1"),
    current_user: dict = Depends(require_login)
):
    try:
        sort = int(sort_order) if sort_order and sort_order.isdigit() else 1
    except ValueError:
        sort = 1

    # 🆕 Ưu tiên upload file ảnh từ máy tính lên Supabase Storage (nén WebP)
    clean_image_url = None
    if image_file and image_file.filename:
        clean_image_url = await upload_image_to_supabase(image_file, folder="guides")
    elif image_url and image_url.strip():
        clean_image_url = image_url.strip()

    clean_video_url = video_url.strip() if video_url and video_url.strip() else None
    admin_id = _get_admin_id(current_user)

    data = {
        "title": title.strip(),
        "printer_model_id": printer_model_id,
        "description": description.strip() if description else "",
        "image_url": clean_image_url,
        "video_url": clean_video_url,
        "is_active": is_active in ["true", "on", "1"],
        "sort_order": sort,
        "created_by": admin_id
    }

    try:
        res = supabase.table("guide").insert(data).execute()
        if res.data:
            new_guide_id = res.data[0]["id"]
            await auto_generate_and_link_tags(new_guide_id, printer_model_id, title.strip())
        else:
            raise HTTPException(status_code=500, detail="Không thể tạo bài viết mới trong database.")
    except Exception as e:
        logger.error(f"Lỗi khi tạo mới bài hướng dẫn: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống khi tạo bài viết: {str(e)}")

    return RedirectResponse("/admin/guide", status_code=status.HTTP_303_SEE_OTHER)


# =====================================================
# EDIT
# =====================================================

@router.get("/edit/{guide_id}", response_class=HTMLResponse)
async def edit_form(
    request: Request, 
    guide_id: int,
    current_user: dict = Depends(require_login)
):
    _check_guide_permission(guide_id, current_user)

    guide_res = supabase.table("guide").select("*").eq("id", guide_id).execute()
    if not guide_res.data:
        return RedirectResponse("/admin/guide", status_code=status.HTTP_303_SEE_OTHER)

    printers = (
        supabase
        .table("printer_model")
        .select("id, brand, model")
        .order("brand")
        .order("model")
        .execute()
        .data or []
    )

    return templates.TemplateResponse(
        "guide_edit.html",
        {
            "request": request,
            "user": current_user,
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
    image_file: Optional[UploadFile] = File(None),  # 🆕 File ảnh tải mới
    image_url: Optional[str] = Form(None),          # Link ảnh cũ hoặc đường dẫn URL
    video_url: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    sort_order: Optional[str] = Form("1"),
    current_user: dict = Depends(require_login)
):
    _check_guide_permission(guide_id, current_user)

    # 1. Lấy thông tin bài viết cũ để phục vụ dọn dẹp Storage nếu đổi ảnh
    old_guide_res = supabase.table("guide").select("image_url").eq("id", guide_id).execute()
    old_image_url = old_guide_res.data[0].get("image_url") if old_guide_res.data else None

    clean_image_url = image_url.strip() if image_url and image_url.strip() else None

    # 2. Xử lý upload ảnh mới & xóa ảnh cũ trên Storage
    if image_file and image_file.filename:
        clean_image_url = await upload_image_to_supabase(image_file, folder="guides")
        # 🗑️ Nếu upload ảnh mới thành công, xóa ngay ảnh cũ trên Storage
        if old_image_url and old_image_url != clean_image_url:
            delete_image_from_supabase(old_image_url)

    clean_video_url = video_url.strip() if video_url and video_url.strip() else None

    update = {
        "title": title.strip(),
        "printer_model_id": printer_model_id,
        "description": description.strip() if description else "",
        "image_url": clean_image_url,
        "video_url": clean_video_url,
        "is_active": is_active in ["true", "on", "1"],
        "sort_order": int(sort_order) if sort_order and sort_order.isdigit() else 1
    }

    try:
        res = supabase.table("guide").update(update).eq("id", guide_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy bài viết để cập nhật")
        
        await auto_generate_and_link_tags(guide_id, printer_model_id, title.strip())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi cập nhật bài hướng dẫn #{guide_id}: {e}")
        raise HTTPException(status_code=500, detail="Không thể cập nhật bài viết")

    return RedirectResponse("/admin/guide", status_code=status.HTTP_303_SEE_OTHER)


# =====================================================
# DELETE
# =====================================================

@router.post("/delete/{guide_id}")
async def delete_guide(
    guide_id: int,
    current_user: dict = Depends(require_login)
):
    _check_guide_permission(guide_id, current_user)

    try:
        # 1. Quét thông tin bài viết gốc để thu thập tất cả link ảnh đại diện
        guide_res = supabase.table("guide").select("image_url").eq("id", guide_id).execute()
        main_image_url = guide_res.data[0].get("image_url") if guide_res.data else None

        # 2. Quét danh sách các bước lớn (guide_step) & lấy ID + link ảnh
        steps_res = supabase.table("guide_step").select("id, image_urls").eq("guide_id", guide_id).execute()
        steps_data = steps_res.data or []
        step_ids = [s["id"] for s in steps_data]
        
        # Gom các URL ảnh từ guide_step (hỗ trợ cả chuỗi đơn hoặc list ảnh)
        step_images = []
        for step in steps_data:
            img = step.get("image_urls")
            if isinstance(img, list):
                step_images.extend(img)
            elif isinstance(img, str) and img:
                step_images.append(img)

        # 3. Quét danh sách các bước nhỏ (guide_sub_steps) lấy link ảnh
        sub_step_images = []
        if step_ids:
            sub_res = supabase.table("guide_sub_steps").select("image_url").in_("step_id", step_ids).execute()
            sub_step_images = [sub["image_url"] for sub in (sub_res.data or []) if sub.get("image_url")]

        # 🗑️ 4. Xóa dữ liệu trong Database (Tuân thủ thứ tự xóa từ bảng con -> bảng mẹ)
        if step_ids:
            supabase.table("guide_sub_steps").delete().in_("step_id", step_ids).execute()
        
        supabase.table("guide_tags").delete().eq("guide_id", guide_id).execute()
        supabase.table("guide_step").delete().eq("guide_id", guide_id).execute()
        supabase.table("guide").delete().eq("id", guide_id).execute()

        # 🗑️ 5. Dọn dẹp tất cả các file ảnh liên quan trên Storage
        if main_image_url:
            delete_image_from_supabase(main_image_url)
        for img_url in set(step_images + sub_step_images):
            delete_image_from_supabase(img_url)

    except Exception as e:
        logger.error(f"Lỗi khi xóa bài hướng dẫn #{guide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể xóa bài viết: {str(e)}")
        
    return RedirectResponse("/admin/guide", status_code=status.HTTP_303_SEE_OTHER)


# =====================================================
# COPY
# =====================================================

@router.post("/copy/{guide_id}")
async def copy_guide(
    guide_id: int,
    current_user: dict = Depends(require_login)
):
    try:
        admin_id = _get_admin_id(current_user)
        
        # 1. Lấy thông tin bài viết gốc
        guide_res = (
            supabase.table("guide")
            .select("*")
            .eq("id", guide_id)
            .execute()
        )
        if not guide_res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy bài viết gốc!")
        
        original_guide = guide_res.data[0]
        
        # 2. Chuẩn bị dữ liệu bài viết mới (Dùng lại image_url cũ, tránh duplicate file trên Storage)
        new_guide_data = {
            "printer_model_id": original_guide.get("printer_model_id"),
            "title": f"{original_guide['title']} (Bản sao)",
            "description": original_guide.get("description"),
            "image_url": original_guide.get("image_url"),
            "video_url": original_guide.get("video_url"),
            "sort_order": (original_guide.get("sort_order") or 1) + 1,
            "is_active": False,
            "is_pinned": False,
            "created_by": admin_id
        }
        
        # 3. Thêm bản ghi Guide mới
        insert_guide_res = supabase.table("guide").insert(new_guide_data).execute()
        if not insert_guide_res.data:
            raise HTTPException(status_code=500, detail="Không thể tạo bản sao bài viết.")
            
        new_guide = insert_guide_res.data[0]
        new_guide_id = new_guide["id"]
        
        # 4. Sao chép các bước lớn (bảng public.guide_step)
        steps_res = (
            supabase.table("guide_step")
            .select("*")
            .eq("guide_id", guide_id)
            .order("step_number")
            .execute()
        )
        
        if steps_res.data:
            old_steps = steps_res.data
            new_steps_payload = [
                {
                    "guide_id": new_guide_id,
                    "step_number": step.get("step_number"),
                    "title": step.get("title"),
                    "content": step.get("content"),
                    "image_urls": step.get("image_urls"),
                    "note": step.get("note"),
                    "is_active": step.get("is_active", True),
                    "video_url": step.get("video_url"),
                    "download_url": step.get("download_url"),
                }
                for step in old_steps
            ]
            
            # Thêm mới danh sách guide_step
            insert_steps_res = supabase.table("guide_step").insert(new_steps_payload).execute()
            new_steps = insert_steps_res.data or []

            # Tạo bản đồ ánh xạ ID bước cũ -> ID bước mới
            step_id_map = {
                old_step["id"]: new_step["id"]
                for old_step, new_step in zip(old_steps, new_steps)
            }

            # 5. Sao chép các bước nhỏ (bảng public.guide_sub_steps)
            old_step_ids = list(step_id_map.keys())
            if old_step_ids:
                sub_steps_res = (
                    supabase.table("guide_sub_steps")
                    .select("*")
                    .in_("step_id", old_step_ids)
                    .order("sub_order")
                    .execute()
                )

                if sub_steps_res.data:
                    new_sub_steps_payload = [
                        {
                            "step_id": step_id_map[sub_step["step_id"]],
                            "sub_order": sub_step.get("sub_order", 1),
                            "content": sub_step.get("content", ""),
                            "image_url": sub_step.get("image_url"),
                            "note": sub_step.get("note"),
                        }
                        for sub_step in sub_steps_res.data
                    ]
                    
                    # Insert danh sách bước nhỏ vào bảng guide_sub_steps
                    supabase.table("guide_sub_steps").insert(new_sub_steps_payload).execute()

        # 6. Tự động đồng bộ Tags cho bài viết mới
        if new_guide_data["printer_model_id"]:
            await auto_generate_and_link_tags(
                new_guide_id, 
                new_guide_data["printer_model_id"], 
                new_guide_data["title"]
            )

        return {
            "success": True,
            "message": "Sao chép bài viết và đầy đủ các bước thành công!",
            "new_guide_id": new_guide_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi sao chép bài viết #{guide_id}: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Lỗi hệ thống khi sao chép bài viết: {str(e)}"
        )
# =====================================================
# DETAIL
# =====================================================
@router.get("/{guide_id}", response_class=HTMLResponse)
async def view_guide(
    request: Request, 
    guide_id: int,
    current_user: dict = Depends(require_login)
):
    # 1. Query bài viết cơ bản
    res = (
        supabase
        .table("guide")
        .select("*, guide_tags(tag_id, tags(*))")
        .eq("id", guide_id)
        .execute()
    )

    if not res.data:
        return RedirectResponse("/admin/guide")

    guide = res.data[0]

    # 2. Lấy thông tin Tác giả thủ công bằng created_by (Giống hệt logic trang list_guides)
    created_by_id = guide.get("created_by")
    if created_by_id:
        try:
            author_res = (
                supabase
                .table("quan_tri_vien")
                .select("ho_ten, username")
                .eq("id", created_by_id)
                .execute()
            )
            if author_res.data:
                guide["quan_tri_vien"] = author_res.data[0]
            else:
                guide["quan_tri_vien"] = None
        except Exception as e:
            logger.warning(f"Lỗi khi lấy tác giả cho guide #{guide_id}: {e}")
            guide["quan_tri_vien"] = None
    else:
        guide["quan_tri_vien"] = None

    # 3. Lấy thông tin máy in
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