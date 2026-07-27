from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from app.database import supabase  
from fastapi.responses import HTMLResponse


router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def home(request: Request):
    try:
        # Truy vấn lấy tối đa 5 bài viết mới nhất từ bảng "guide"
        res = (
            supabase.table("guide")
            .select("*")
            .order("created_at", desc=True)  # Sắp xếp theo mới nhất (hoặc đổi thành "id" nếu bảng không có created_at)
            .limit(3)
            .execute()
        )
        recent_guides = res.data or []
    except Exception as e:
        recent_guides = []

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Trang chủ",
            "recent_guides": recent_guides  # Truyền dữ liệu sang giao diện index.html
        }
    )
@router.get("/search", response_class=HTMLResponse)
async def search_guides(request: Request, q: str = ""):
    keyword = q.strip()
    search_results = []
    
    try:
        if keyword:
            # 1. Tìm tất cả bài viết có tiêu đề khớp với từ khóa
            title_res = (
                supabase.table("guide")
                .select("*")
                .ilike("title", f"%{keyword}%")
                .execute()
            )
            title_matches = title_res.data or []
            
            # 2. Tìm tất cả các model máy in khớp với từ khóa (lấy từ cuối, ví dụ "g3010")
            parts = keyword.split()
            model_keyword = parts[-1] if parts else keyword
            
            model_res = (
                supabase.table("printer_model")
                .select("id")
                .ilike("model", f"%{model_keyword}%")
                .execute()
            )
            matched_model_ids = [m["id"] for m in (model_res.data or [])]
            
            model_matches = []
            if matched_model_ids:
                guide_res = (
                    supabase.table("guide")
                    .select("*")
                    .in_("printer_model_id", matched_model_ids)
                    .execute()
                )
                model_matches = guide_res.data or []
            
            # 3. Gộp cả 2 danh sách lại và loại bỏ bài viết trùng lặp dựa theo ID
            combined_dict = {guide["id"]: guide for guide in title_matches + model_matches}
            search_results = list(combined_dict.values())

    except Exception as e:
        search_results = []

    # Trả về đúng giao diện trang kết quả tìm kiếm riêng biệt
    return templates.TemplateResponse(
        "search_results.html",
        {
            "request": request,
            "keyword": keyword,
            "guides": search_results
        }
    )
# --- BỔ SUNG ROUTE XEM CHI TIẾT BÀI HƯỚNG DẪN CHO KHÁCH ---
@router.get("/guide/{guide_id}", response_class=HTMLResponse)
async def view_guide_detail(request: Request, guide_id: int):
    try:
        # 1. Lấy thông tin bài hướng dẫn chính
        guide_res = supabase.table("guide").select("*, printer_model(brand, model)").eq("id", guide_id).execute()
        if not guide_res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy bài hướng dẫn")
        guide = guide_res.data[0]

        # 2. Lấy danh sách các bước lớn (chỉ lấy các bước đang active nếu muốn, hoặc lấy tất cả)
        steps_res = (
            supabase.table("guide_step")
            .select("*")
            .eq("guide_id", guide_id)
            .eq("is_active", True) # Chỉ hiện các bước được bật hiển thị
            .order("step_number")
            .execute()
        )
        steps = steps_res.data or []

        # 3. Lấy thêm các bước con (sub_steps) cho từng bước lớn
        for step in steps:
            sub_res = (
                supabase.table("guide_sub_steps")
                .select("*")
                .eq("step_id", step["id"])
                .order("sub_order")
                .execute()
            )
            step["sub_steps"] = sub_res.data or []

    except Exception as e:
        raise HTTPException(status_code=404, detail="Không thể tải nội dung bài viết")

    # Trả về template hiển thị dành riêng cho khách (hoàn toàn thuần túy, không có form sửa xóa)
    return templates.TemplateResponse(
        "guide_detail.html",  # Tên file template giao diện đọc của khách
        {
            "request": request,
            "guide": guide,
            "steps": steps
        }
    )
