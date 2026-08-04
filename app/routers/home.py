import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.database import supabase  

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def home(request: Request):
    try:
        # Chỉ lấy các bài viết đang được active
        res = (
            supabase.table("guide")
            .select("*")
            .eq("is_active", True)
            .order("id", desc=True) # Dùng 'id' desc an toàn hơn nếu bảng không có 'created_at'
            .limit(3)
            .execute()
        )
        recent_guides = res.data or []
    except Exception as e:
        logger.error(f"Lỗi load trang chủ: {e}")
        recent_guides = []

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Trang chủ",
            "recent_guides": recent_guides
        }
    )


@router.get("/search", response_class=HTMLResponse)
async def search_guides(request: Request, q: str = ""):
    keyword = q.strip()
    search_results = []
    
    try:
        if keyword:
            # 1. Tìm tất cả bài viết có tiêu đề khớp với từ khóa VÀ đang active
            title_res = (
                supabase.table("guide")
                .select("*")
                .eq("is_active", True)
                .ilike("title", f"%{keyword}%")
                .execute()
            )
            title_matches = title_res.data or []
            
            # 2. Tìm Model máy in linh hoạt hơn (Tìm thẳng keyword trong cả brand và model)
            # Thay vì chỉ lấy từ cuối cùng, ta dùng toán tử OR của Supabase
            model_res = (
                supabase.table("printer_model")
                .select("id")
                .or_(f"brand.ilike.%{keyword}%,model.ilike.%{keyword}%")
                .execute()
            )
            matched_model_ids = [m["id"] for m in (model_res.data or [])]
            
            model_matches = []
            if matched_model_ids:
                guide_res = (
                    supabase.table("guide")
                    .select("*")
                    .eq("is_active", True)
                    .in_("printer_model_id", matched_model_ids)
                    .execute()
                )
                model_matches = guide_res.data or []
            
            # 3. Gộp 2 danh sách và loại bỏ bài viết trùng lặp (dựa theo ID)
            combined_dict = {guide["id"]: guide for guide in title_matches + model_matches}
            search_results = list(combined_dict.values())

    except Exception as e:
        logger.error(f"Lỗi tìm kiếm với từ khóa '{keyword}': {e}")
        search_results = []

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
        # 1. Lấy thông tin bài hướng dẫn chính và yêu cầu phải đang ACTIVE
        guide_res = (
            supabase.table("guide")
            .select("*, printer_model(brand, model)")
            .eq("id", guide_id)
            .eq("is_active", True) 
            .execute()
        )
        if not guide_res.data:
            raise HTTPException(status_code=404, detail="Không tìm thấy bài hướng dẫn hoặc bài viết đã bị ẩn")
        guide = guide_res.data[0]

        # 2. Lấy danh sách các bước lớn đang active
        steps_res = (
            supabase.table("guide_step")
            .select("*")
            .eq("guide_id", guide_id)
            .eq("is_active", True)
            .order("step_number")
            .execute()
        )
        steps = steps_res.data or []

        # 3. TỐI ƯU HÓA: Tránh N+1 Query bằng cách lấy toàn bộ sub_steps trong 1 lần gọi
        if steps:
            step_ids = [step["id"] for step in steps]
            sub_res = (
                supabase.table("guide_sub_steps")
                .select("*")
                .in_("step_id", step_ids)
                .order("sub_order")
                .execute()
            )
            all_sub_steps = sub_res.data or []

            # Phân bổ sub_steps về đúng step_id của nó
            sub_map = {sid: [] for sid in step_ids}
            for sub in all_sub_steps:
                sub_map[sub["step_id"]].append(sub)
            
            for step in steps:
                step["sub_steps"] = sub_map.get(step["id"], [])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi load chi tiết bài guide #{guide_id}: {e}")
        raise HTTPException(status_code=500, detail="Lỗi máy chủ khi tải nội dung bài viết")

    return templates.TemplateResponse(
        "guide_detail.html",
        {
            "request": request,
            "guide": guide,
            "steps": steps
        }
    )