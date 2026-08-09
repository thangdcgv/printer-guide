import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.config import templates
from app.database import supabase
from app.routers.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Dashboard"])


# =========================================================
# HELPER: LẤY DỮ LIỆU THỐNG KÊ
# =========================================================

def fetch_dashboard_stats():
    """Hàm dùng chung để lấy dữ liệu thống kê máy in và bài viết."""
    try:
        models_res = supabase.table("printer_model").select("*").execute()
        printer_models = models_res.data or []

        guides_res = supabase.table("guide").select("*").execute()
        guides = guides_res.data or []

        total_guides = len(guides)
        total_models = len(printer_models)

        model_map = {
            m["id"]: {
                "display_name": f"{m.get('brand', '')} - {m.get('model', '')}",
                "brand": m.get("brand", ""),
                "count": 0,
            }
            for m in printer_models
        }

        other_guides_count = 0
        for g in guides:
            m_id = g.get("printer_model_id") or g.get("model_id")
            if m_id and m_id in model_map:
                model_map[m_id]["count"] += 1
            else:
                other_guides_count += 1

        category_stats = [
            {
                "name": info["display_name"],
                "brand": info["brand"],
                "count": info["count"],
            }
            for info in model_map.values()
        ]

        if other_guides_count > 0:
            category_stats.append({
                "name": "Tài liệu chung / Khác",
                "brand": "Chung",
                "count": other_guides_count,
            })

        return total_guides, total_models, category_stats

    except Exception as e:
        logger.error("Lỗi lấy dữ liệu dashboard: %s", e)
        return 0, 0, []


# =========================================================
# 1. PUBLIC DASHBOARD (Dành cho truy cập từ Trang chủ Index)
# =========================================================

@router.get("/dashboard", response_class=HTMLResponse)
async def public_dashboard(request: Request):
    """
    Trang thống kê công khai. Người dùng từ Index có thể xem
    mà không bị bắt đăng nhập.
    """
    total_guides, total_models, category_stats = fetch_dashboard_stats()

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "total_guides": total_guides,
            "total_models": total_models,
            "category_stats": category_stats,
            "admin": None,  # Khách chưa đăng nhập
        },
    )


# =========================================================
# 2. ADMIN DASHBOARD (Dành riêng cho Quản trị viên)
# =========================================================

@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin: dict = Depends(require_admin),  # Xác thực chuẩn qua require_admin
):
    """
    Trang Dashboard quản trị. Yêu cầu đăng nhập Admin.
    """
    total_guides, total_models, category_stats = fetch_dashboard_stats()

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "admin": admin,  # Truyền thông tin admin vào template
            "total_guides": total_guides,
            "total_models": total_models,
            "category_stats": category_stats,
        },
    )