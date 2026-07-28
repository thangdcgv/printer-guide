from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.database import supabase  

router = APIRouter(prefix="/admin/library", tags=["Library Management"])
templates = Jinja2Templates(directory="app/templates")

# 1. Trang chủ thư viện (Hiển thị thư mục và tài nguyên)
@router.get("", response_class=HTMLResponse)
async def library_home(request: Request, folder_id: int = None):
    try:
        current_folder = None
        sub_folders = []
        resources = []

        if folder_id:
            # 1. Lấy thông tin thư mục hiện tại
            f_res = supabase.table("library_folder").select("*").eq("id", folder_id).execute()
            if f_res.data:
                current_folder = f_res.data[0]
            
            # 2. Lấy các thư mục con bên trong
            sf_res = (
                supabase.table("library_folder")
                .select("*")
                .eq("parent_id", folder_id)
                .order("sort_order")
                .execute()
            )
            sub_folders = sf_res.data or []
            
            # 3. CHỈ lấy tài nguyên nằm TRONG thư mục này
            r_res = (
                supabase.table("library_resource")
                .select("*")
                .eq("folder_id", folder_id)
                .execute()
            )
            resources = r_res.data or []
        else:
            # Nếu ở thư mục gốc (Root): lấy các thư mục gốc
            sf_res = (
                supabase.table("library_folder")
                .select("*")
                .is_("parent_id", "null")
                .order("sort_order")
                .execute()
            )
            sub_folders = sf_res.data or []
            
            # CHỈ lấy tài nguyên nằm ở gốc (folder_id là NULL)
            r_res = (
                supabase.table("library_resource")
                .select("*")
                .is_("folder_id", "null")
                .execute()
            )
            resources = r_res.data or []

    except Exception as e:
        sub_folders, resources = [], []

    return templates.TemplateResponse(
        "admin/library.html",
        {
            "request": request,
            "current_folder": current_folder,
            "sub_folders": sub_folders,
            "resources": resources,
            "folder_id": folder_id
        }
    )

# 2. Trang form thêm thư mục mới (Khớp với nút bấm của bạn)
@router.get("/folder/create", response_class=HTMLResponse)
async def create_folder_page(request: Request, parent_id: int = None):
    return templates.TemplateResponse(
        "admin/library_folder_form.html",
        {"request": request, "parent_id": parent_id}
    )

@router.post("/folder/create")
async def create_folder_submit(name: str = Form(...), parent_id: int = Form(None), description: str = Form(None)):
    try:
        supabase.table("library_folder").insert({
            "name": name,
            "parent_id": parent_id if parent_id else None,
            "description": description
        }).execute()
    except Exception as e:
        pass
    
    redirect_url = f"/admin/library?folder_id={parent_id}" if parent_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=303)

# 3. Trang form thêm tài nguyên / OneDrive (Khớp với nút Tải tệp lên / Thêm tài nguyên)
@router.get("/upload", response_class=HTMLResponse)
@router.get("/resource/create", response_class=HTMLResponse)
async def create_resource_page(request: Request, folder_id: int = None):
    try:
        # Lấy tất cả thư mục để hiển thị trong thẻ chọn (dropdown)
        folders_res = supabase.table("library_folder").select("id, name").order("name").execute()
        folders = folders_res.data or []
    except Exception as e:
        folders = []

    return templates.TemplateResponse(
        "admin/library_resource_form.html",
        {
            "request": request, 
            "folder_id": folder_id,
            "folders": folders
        }
    )

@router.post("/resource/create")
async def create_resource_submit(
    title: str = Form(...),
    folder_id: int = Form(...),
    resource_type: str = Form(...),
    url: str = Form(...),
    description: str = Form(None)
):
    try:
        supabase.table("library_resource").insert({
            "title": title,
            "folder_id": folder_id,
            "resource_type": resource_type,
            "url": url,
            "description": description
        }).execute()
    except Exception as e:
        pass
        
    return RedirectResponse(url=f"/admin/library?folder_id={folder_id}", status_code=303)
# --- XỬ LÝ THƯ MỤC (FOLDER) ---

@router.get("/folder/edit/{folder_id}", response_class=HTMLResponse)
async def edit_folder_page(request: Request, folder_id: int):
    f_res = supabase.table("library_folder").select("*").eq("id", folder_id).execute()
    if not f_res.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục")
    return templates.TemplateResponse("admin/library_folder_edit.html", {"request": request, "folder": f_res.data[0]})

@router.post("/folder/edit/{folder_id}")
async def edit_folder_submit(folder_id: int, name: str = Form(...), description: str = Form(None)):
    f_res = supabase.table("library_folder").select("parent_id").eq("id", folder_id).execute()
    parent_id = f_res.data[0].get("parent_id") if f_res.data else None
    
    supabase.table("library_folder").update({
        "name": name,
        "description": description
    }).eq("id", folder_id).execute()
    
    redirect_url = f"/admin/library?folder_id={parent_id}" if parent_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=303)

@router.get("/folder/delete/{folder_id}")
async def delete_folder(folder_id: int):
    f_res = supabase.table("library_folder").select("parent_id").eq("id", folder_id).execute()
    parent_id = f_res.data[0].get("parent_id") if f_res.data else None
    
    # Xóa thư mục (Các bảng con/tài liệu liên quan sẽ tự động xóa nếu thiết lập CASCADE trên DB)
    supabase.table("library_folder").delete().eq("id", folder_id).execute()
    
    redirect_url = f"/admin/library?folder_id={parent_id}" if parent_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=303)


# --- XỬ LÝ TÀI NGUYÊN (RESOURCE) ---

@router.get("/resource/edit/{resource_id}", response_class=HTMLResponse)
async def edit_resource_page(request: Request, resource_id: int):
    r_res = supabase.table("library_resource").select("*").eq("id", resource_id).execute()
    if not r_res.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài nguyên")
    
    folders_res = supabase.table("library_folder").select("id, name").order("name").execute()
    folders = folders_res.data or []
    
    return templates.TemplateResponse("admin/library_resource_edit.html", {
        "request": request, 
        "resource": r_res.data[0],
        "folders": folders
    })

@router.post("/resource/edit/{resource_id}")
async def edit_resource_submit(
    resource_id: int,
    title: str = Form(...),
    folder_id: int = Form(...),
    resource_type: str = Form(...),
    url: str = Form(...),
    description: str = Form(None)
):
    supabase.table("library_resource").update({
        "title": title,
        "folder_id": folder_id,
        "resource_type": resource_type,
        "url": url,
        "description": description
    }).eq("id", resource_id).execute()
    
    return RedirectResponse(url=f"/admin/library?folder_id={folder_id}", status_code=303)

@router.get("/resource/delete/{resource_id}")
async def delete_resource(resource_id: int):
    r_res = supabase.table("library_resource").select("folder_id").eq("id", resource_id).execute()
    folder_id = r_res.data[0].get("folder_id") if r_res.data else None
    
    supabase.table("library_resource").delete().eq("id", resource_id).execute()
    
    redirect_url = f"/admin/library?folder_id={folder_id}" if folder_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=303)