import io
import uuid
from fastapi import UploadFile, HTTPException
from PIL import Image, ImageOps
from urllib.parse import urlparse

# Import trực tiếp client Supabase đã khởi tạo sẵn từ config
from app.config import supabase  

BUCKET_NAME = "library-images"

def _compress_to_webp(file_bytes: bytes, max_size=(1200, 1200), quality=75) -> bytes:
    """Hàm nội bộ: Nén ảnh và chuyển đổi sang WebP"""
    image = Image.open(io.BytesIO(file_bytes))
    
    # Auto rotate theo EXIF (ảnh chụp điện thoại)
    if hasattr(image, '_getexif') and image._getexif() is not None:
        image = ImageOps.exif_transpose(image)

    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
        
    image.thumbnail(max_size)
    
    output_buffer = io.BytesIO()
    image.save(output_buffer, format="WEBP", quality=quality, optimize=True)
    return output_buffer.getvalue()

async def upload_image_to_supabase(file: UploadFile, folder: str = "general") -> str:
    """
    Hàm dùng chung: Kiểm tra, nén và upload ảnh lên Supabase Storage.
    Trả về: Public URL của ảnh.
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File không đúng định dạng hình ảnh.")

    try:
        raw_bytes = await file.read()
        webp_bytes = _compress_to_webp(raw_bytes)
        
        # Đường dẫn lưu: ví dụ guides/550e8400-e29b-41d4-a716-446655440000.webp
        filename = f"{folder}/{uuid.uuid4()}.webp"
        
        supabase.storage.from_(BUCKET_NAME).upload(
            path=filename,
            file=webp_bytes,
            file_options={"content-type": "image/webp"}
        )
        
        return supabase.storage.from_(BUCKET_NAME).get_public_url(filename)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi upload ảnh: {str(e)}")
    
def delete_image_from_supabase(image_url: str):
    """
    Xóa file ảnh trên Supabase Storage dựa vào public URL.
    """
    if not image_url or BUCKET_NAME not in image_url:
        return

    try:
        # 1. Cắt bỏ Query Parameters (ví dụ: ?t=123456) nếu có
        parsed_url = urlparse(image_url)
        clean_path_url = parsed_url.path 

        # 2. Tách lấy relative path chính xác (ví dụ: "guides/uuid.webp")
        pattern = f"/public/{BUCKET_NAME}/"
        if pattern not in clean_path_url:
            return

        storage_path = clean_path_url.split(pattern)[-1]
        
        # Bỏ dấu / ở đầu nếu có
        if storage_path.startswith("/"):
            storage_path = storage_path[1:]

        # 3. Thực thi xóa file trên Supabase
        res = supabase.storage.from_(BUCKET_NAME).remove([storage_path])
        print(f"[Storage Delete] Xóa file thành công: {storage_path} | Phản hồi: {res}")

    except Exception as e:
        print(f"[Warning] Không thể xóa ảnh trên Storage ({image_url}): {e}")