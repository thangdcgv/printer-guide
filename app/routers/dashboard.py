from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import supabase
from app.config import templates

router = APIRouter(prefix="/admin", tags=["Dashboard"])

def verify_session(request: Request):
    user_session = request.cookies.get("user_session")
    if not user_session:
        return None
    return user_session

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not verify_session(request):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        # 1. Lấy toàn bộ danh sách dòng máy in từ bảng printer_model
        models_res = supabase.table("printer_model").select("*").execute()
        printer_models = models_res.data or []

        # 2. Lấy toàn bộ danh sách bài viết hướng dẫn từ bảng guide
        guides_res = supabase.table("guide").select("*").execute()
        guides = guides_res.data or []

        total_guides = len(guides)
        total_models = len(printer_models)

        # 3. Tạo từ điển ánh xạ ID model sang tên model/brand để hiển thị dễ hiểu
        # Ví dụ: { 1: {"name": "Canon PRO-1000", "brand": "Canon"}, ... }
        model_map = {}
        for m in printer_models:
            model_map[m["id"]] = {
                "display_name": f"{m['brand']} - {m['model']}",
                "brand": m["brand"],
                "count": 0
            }

        # 4. Đếm số lượng tài liệu hướng dẫn cho từng dòng máy
        # (Giả định bảng guide có cột 'printer_model_id' hoặc 'model_id' liên kết với printer_model.id)
        other_guides_count = 0
        for guide in guides:
            # Kiểm tra tên cột liên kết trong bảng guide của bạn (có thể là printer_model_id hoặc model_id)
            m_id = guide.get("printer_model_id") or guide.get("model_id")
            if m_id and m_id in model_map:
                model_map[m_id]["count"] += 1
            else:
                other_guides_count += 1

        # Chuyển đổi dữ liệu sang dạng list để đưa ra giao diện
        category_stats = [
            {
                "name": info["display_name"],
                "brand": info["brand"],
                "count": info["count"]
            }
            for info in model_map.values()
        ]

        # Nếu có bài viết nào chưa gắn model, gộp vào mục "Khác / Chung"
        if other_guides_count > 0:
            category_stats.append({
                "name": "Tài liệu chung / Khác",
                "brand": "Chung",
                "count": other_guides_count
            })

    except Exception as e:
        total_guides = 0
        total_models = 0
        category_stats = []

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "total_guides": total_guides,
            "total_models": total_models,
            "category_stats": category_stats
        }
    )