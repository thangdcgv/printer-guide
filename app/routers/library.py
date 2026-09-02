import logging
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import templates
from app.database import supabase
from app.routers.auth import require_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/library", tags=["Library Management"])


# 1. Trang chủ thư viện (Hiển thị thư mục và tài nguyên)
@router.get("", response_class=HTMLResponse)
def library_home(
    request: Request,
    folder_id: Optional[int] = None,
    current_user: dict = Depends(require_login),
):
    current_folder = None
    sub_folders = []
    resources = []

    try:
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
            # Ở thư mục gốc (Root): lấy các thư mục có parent_id là NULL
            sf_res = (
                supabase.table("library_folder")
                .select("*")
                .is_("parent_id", None)
                .order("sort_order")
                .execute()
            )
            sub_folders = sf_res.data or []

            # CHỈ lấy tài nguyên nằm ở gốc (folder_id là NULL)
            r_res = (
                supabase.table("library_resource")
                .select("*")
                .is_("folder_id", None)
                .execute()
            )
            resources = r_res.data or []

    except Exception as e:
        logger.error("Lỗi khi tải danh sách thư viện: %s", e, exc_info=True)
        sub_folders, resources = [], []

    return templates.TemplateResponse(
        "admin/library.html",
        {
            "request": request,
            "current_folder": current_folder,
            "sub_folders": sub_folders,
            "resources": resources,
            "folder_id": folder_id,
            "current_user": current_user,
            "admin": current_user,
        },
    )


# 2. Trang form thêm thư mục mới
@router.get("/folder/create", response_class=HTMLResponse)
def create_folder_page(
    request: Request,
    parent_id: Optional[int] = None,
    current_user: dict = Depends(require_login),
):
    return templates.TemplateResponse(
        "admin/library_folder_form.html",
        {
            "request": request,
            "parent_id": parent_id,
            "current_user": current_user,
            "admin": current_user,
        },
    )


@router.post("/folder/create")
def create_folder_submit(
    name: str = Form(...),
    parent_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    current_user: dict = Depends(require_login),
):
    try:
        supabase.table("library_folder").insert({
            "name": name.strip(),
            "parent_id": parent_id if parent_id else None,
            "description": description.strip() if description else None,
        }).execute()
    except Exception as e:
        logger.error("Lỗi khi tạo thư mục mới: %s", e, exc_info=True)

    redirect_url = f"/admin/library?folder_id={parent_id}" if parent_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


# 3. Trang form thêm tài nguyên / OneDrive
@router.get("/upload", response_class=HTMLResponse)
@router.get("/resource/create", response_class=HTMLResponse)
def create_resource_page(
    request: Request,
    folder_id: Optional[int] = None,
    current_user: dict = Depends(require_login),
):
    try:
        folders_res = supabase.table("library_folder").select("id, name").order("name").execute()
        folders = folders_res.data or []
    except Exception as e:
        logger.error("Lỗi khi lấy danh sách thư mục: %s", e, exc_info=True)
        folders = []

    return templates.TemplateResponse(
        "admin/library_resource_form.html",
        {
            "request": request,
            "folder_id": folder_id,
            "folders": folders,
            "current_user": current_user,
            "admin": current_user,
        },
    )


@router.post("/resource/create")
def create_resource_submit(
    title: str = Form(...),
    resource_type: str = Form(...),
    url: str = Form(...),
    folder_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    current_user: dict = Depends(require_login),
):
    try:
        supabase.table("library_resource").insert({
            "title": title.strip(),
            "folder_id": folder_id if folder_id else None,
            "resource_type": resource_type.strip(),
            "url": url.strip(),
            "description": description.strip() if description else None,
        }).execute()
    except Exception as e:
        logger.error("Lỗi khi tạo tài nguyên mới: %s", e, exc_info=True)

    redirect_url = f"/admin/library?folder_id={folder_id}" if folder_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


# --- XỬ LÝ THƯ MỤC (FOLDER) ---

@router.get("/folder/edit/{folder_id}", response_class=HTMLResponse)
def edit_folder_page(
    request: Request,
    folder_id: int,
    current_user: dict = Depends(require_login),
):
    f_res = supabase.table("library_folder").select("*").eq("id", folder_id).execute()
    if not f_res.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư mục")

    return templates.TemplateResponse(
        "admin/library_folder_edit.html",
        {
            "request": request,
            "folder": f_res.data[0],
            "current_user": current_user,
            "admin": current_user,
        },
    )


@router.post("/folder/edit/{folder_id}")
def edit_folder_submit(
    folder_id: int,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    current_user: dict = Depends(require_login),
):
    f_res = supabase.table("library_folder").select("parent_id").eq("id", folder_id).execute()
    parent_id = f_res.data[0].get("parent_id") if f_res.data else None

    supabase.table("library_folder").update({
        "name": name.strip(),
        "description": description.strip() if description else None,
    }).eq("id", folder_id).execute()

    redirect_url = f"/admin/library?folder_id={parent_id}" if parent_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/folder/delete/{folder_id}")
def delete_folder(
    folder_id: int,
    current_user: dict = Depends(require_login),
):
    f_res = supabase.table("library_folder").select("parent_id").eq("id", folder_id).execute()
    parent_id = f_res.data[0].get("parent_id") if f_res.data else None

    supabase.table("library_folder").delete().eq("id", folder_id).execute()

    redirect_url = f"/admin/library?folder_id={parent_id}" if parent_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


# --- XỬ LÝ TÀI NGUYÊN (RESOURCE) ---

@router.get("/resource/edit/{resource_id}", response_class=HTMLResponse)
def edit_resource_page(
    request: Request,
    resource_id: int,
    current_user: dict = Depends(require_login),
):
    r_res = supabase.table("library_resource").select("*").eq("id", resource_id).execute()
    if not r_res.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài nguyên")

    folders_res = supabase.table("library_folder").select("id, name").order("name").execute()
    folders = folders_res.data or []

    return templates.TemplateResponse(
        "admin/library_resource_edit.html",
        {
            "request": request,
            "resource": r_res.data[0],
            "folders": folders,
            "current_user": current_user,
            "admin": current_user,
        },
    )


@router.post("/resource/edit/{resource_id}")
def edit_resource_submit(
    resource_id: int,
    title: str = Form(...),
    resource_type: str = Form(...),
    url: str = Form(...),
    folder_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    current_user: dict = Depends(require_login),
):
    supabase.table("library_resource").update({
        "title": title.strip(),
        "folder_id": folder_id if folder_id else None,
        "resource_type": resource_type.strip(),
        "url": url.strip(),
        "description": description.strip() if description else None,
    }).eq("id", resource_id).execute()

    redirect_url = f"/admin/library?folder_id={folder_id}" if folder_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/resource/delete/{resource_id}")
def delete_resource(
    resource_id: int,
    current_user: dict = Depends(require_login),
):
    r_res = supabase.table("library_resource").select("folder_id").eq("id", resource_id).execute()
    folder_id = r_res.data[0].get("folder_id") if r_res.data else None

    supabase.table("library_resource").delete().eq("id", resource_id).execute()

    redirect_url = f"/admin/library?folder_id={folder_id}" if folder_id else "/admin/library"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)