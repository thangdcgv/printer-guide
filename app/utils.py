import time
from typing import Dict, Optional
from fastapi import Request

# ---------------------------------------------------------
# 1. HÀM CHUẨN HÓA CHUỖI CỦA BẠN
# ---------------------------------------------------------
def normalize_text(value: str) -> str:
    """
    Chuẩn hóa chuỗi:
    - Bỏ khoảng trắng đầu/cuối
    - Gộp nhiều khoảng trắng thành 1
    - Chuyển thành IN HOA
    """
    if not value:
        return ""
    return " ".join(value.split()).upper()


# ---------------------------------------------------------
# 2. HỆ THỐNG THEO DÕI NGƯỜI DÙNG ONLINE (IN-MEMORY)
# ---------------------------------------------------------

# Bộ nhớ tạm lưu trữ thời gian truy cập cuối cùng:
# Structure: { "ip_or_session_key": {"last_seen": timestamp, "user_id": int | None} }
_active_sessions: Dict[str, dict] = {}

# Thời gian hết hạn (tính bằng giây): Nếu quá 60 giây không có request mới thì tính là Offline
ONLINE_TIMEOUT_SECONDS = 60


def track_user_visit(request: Request, user_id: Optional[int] = None):
    """
    Ghi nhận lượt truy cập của người dùng.
    Gọi hàm này trong Middleware hoặc trong các Route chính.
    """
    now = time.time()
    
    # Lấy IP của người dùng (X-Forwarded-For nếu chạy qua Nginx/Cloudflare, nếu không lấy client.host)
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    # Định danh phiên bằng IP (hoặc có thể dùng Session ID)
    session_key = f"ip_{client_ip}"
    if user_id:
        session_key = f"user_{user_id}"

    _active_sessions[session_key] = {
        "last_seen": now,
        "user_id": user_id,
        "ip": client_ip
    }


def get_online_stats() -> dict:
    """
    Tính toán và trả về số lượng người đang truy cập thực tế.
    Tự động dọn dẹp các session đã quá hạn (Offline).
    """
    now = time.time()
    expired_keys = []

    total_online = 0
    accounts_online = set()

    # Duyệt qua các session đang lưu trong bộ nhớ
    for key, data in list(_active_sessions.items()):
        # Nếu đã quá 60 giây không hoạt động -> Đánh dấu xóa
        if now - data["last_seen"] > ONLINE_TIMEOUT_SECONDS:
            expired_keys.append(key)
        else:
            total_online += 1
            if data.get("user_id"):
                accounts_online.add(data["user_id"])

    # Xóa các key hết hạn để giải phóng bộ nhớ
    for key in expired_keys:
        _active_sessions.pop(key, None)

    return {
        "total_online": total_online,
        "accounts_online": len(accounts_online),
        "guests_online": max(0, total_online - len(accounts_online))
    }