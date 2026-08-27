from fastapi import APIRouter, Response
from app.config import supabase

router = APIRouter(tags=["SEO"])

BASE_URL = "https://printer-guide.onrender.com"

@router.get("/robots.txt", response_class=Response)
def get_robots_txt():
    content = f"""User-agent: *
Allow: /

Sitemap: {BASE_URL}/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@router.get("/sitemap.xml", response_class=Response)
def get_sitemap():
    # 1. Các trang cố định (Static URLs)
    static_urls = [
        {"loc": f"{BASE_URL}/", "priority": "1.0", "changefreq": "daily"},
        {"loc": f"{BASE_URL}/warranty/list", "priority": "0.8", "changefreq": "weekly"},
    ]

    # 2. Lấy động danh sách bài viết/hướng dẫn từ Supabase (Dynamic URLs)
    dynamic_xml = ""
    try:
        # Giả định bảng lưu hướng dẫn của bạn tên là 'guides' hoặc 'libraries'
        # Thay tên bảng và cột phù hợp với DB của bạn nếu cần
        res = supabase.table("guides").select("id, updated_at").execute()
        if res.data:
            for item in res.data:
                guide_id = item.get("id")
                # Thường đường dẫn xem bài viết có dạng /guide/{id} hoặc /library/{id}
                dynamic_xml += f"""
    <url>
        <loc>{BASE_URL}/guide/{guide_id}</loc>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>
    </url>"""
    except Exception as e:
        print(f"⚠️ Không thể lấy bài viết động cho sitemap: {e}")

    # 3. Ghép các trang cố định
    static_xml = ""
    for url in static_urls:
        static_xml += f"""
    <url>
        <loc>{url['loc']}</loc>
        <changefreq>{url['changefreq']}</changefreq>
        <priority>{url['priority']}</priority>
    </url>"""

    # 4. Xuất file XML hoàn chỉnh
    sitemap_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{static_xml}{dynamic_xml}
</urlset>"""

    return Response(content=sitemap_content, media_type="application/xml")