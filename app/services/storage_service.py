import io
import uuid
import logging
from typing import Optional
from urllib.parse import urlparse

from fastapi import UploadFile, HTTPException, status
from PIL import Image, ImageOps

# Import nhất quán từ app.database
from app.database import supabase

logger = logging.getLogger(__name__)

BUCKET_NAME = "library-images"


def _compress_to_webp(file_bytes: bytes, max_size=(1200, 1200), quality=75) -> bytes:
    """
    Hàm nội bộ: Nén ảnh và chuyển đổi sang WebP.
    Xử lý an toàn ảnh có nền trong suốt (RGBA/PNG) để tránh bị đen nền.
    """
    image = Image.open(io.BytesIO(file_bytes))

    # Tự động xoay ảnh đúng chiều theo EXIF metadata (ảnh chụp từ điện thoại)
    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass

    # Xử lý kênh Alpha (nền trong suốt) tránh lỗi đen nền khi đổi sang WebP/RGB
    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        background.paste(image, mask=image.split()[-1] if "A" in image.mode else None)
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    # Resize giảm kích thước nếu lớn hơn max_size
    image.thumbnail(max_size, Image.Resampling.LANCZOS)

    output_buffer = io.BytesIO()
    image.save(output_buffer, format="WEBP", quality=quality, optimize=True)
    return output_buffer.getvalue()


async def upload_image_to_supabase(file: UploadFile, folder: str = "general") -> str:
    """
    Hàm dùng chung: Kiểm tra, nén và upload ảnh lên Supabase Storage.
    Trả về: Public URL của ảnh.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File gửi lên không đúng định dạng hình ảnh.",
        )

    try:
        raw_bytes = await file.read()
        webp_bytes = _compress_to_webp(raw_bytes)

        # Đường dẫn lưu trên bucket: ví dụ guides/550e8400-e29b-41d4-a716-446655440000.webp
        clean_folder = folder.strip("/").strip()
        filename = f"{clean_folder}/{uuid.uuid4()}.webp"

        # Push file lên Supabase Storage
        supabase.storage.from_(BUCKET_NAME).upload(
            path=filename,
            file=webp_bytes,
            file_options={"content-type": "image/webp"},
        )

        return supabase.storage.from_(BUCKET_NAME).get_public_url(filename)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Lỗi khi nén và upload ảnh lên Supabase: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể tải ảnh lên hệ thống: {str(e)}",
        )


def delete_image_from_supabase(image_url: Optional[str]) -> bool:
    """
    Xóa file ảnh trên Supabase Storage dựa vào public URL.
    """
    if not image_url or BUCKET_NAME not in image_url:
        return False

    try:
        # 1. Loại bỏ Query Parameters (ví dụ: ?t=123456)
        parsed_url = urlparse(image_url)
        clean_path_url = parsed_url.path

        # 2. Tách lấy relative path chính xác (ví dụ: "guides/uuid.webp")
        pattern = f"/{BUCKET_NAME}/"
        if pattern not in clean_path_url:
            return False

        storage_path = clean_path_url.split(pattern)[-1]

        # Bỏ dấu / ở đầu path nếu có
        if storage_path.startswith("/"):
            storage_path = storage_path[1:]

        # 3. Thực hiện xóa file trên Storage
        res = supabase.storage.from_(BUCKET_NAME).remove([storage_path])
        logger.info("Đã xóa file trên Supabase Storage: %s | Response: %s", storage_path, res)
        return True

    except Exception as e:
        logger.warning("Không thể xóa ảnh trên Storage (%s): %s", image_url, e)
        return False