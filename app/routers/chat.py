from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.ai_service import search_guides_and_answer

router = APIRouter(prefix="/api/chat", tags=["AI Chatbot"])

class ChatRequest(BaseModel):
    message: str

# Danh sách từ khóa nhận diện
SALES_KEYWORDS = ["mua", "bán", "báo giá", "giá bao nhiêu", "đặt mua", "mua hàng", "tư vấn mua"]
TECH_KEYWORDS = ["kỹ thuật", "gặp thợ", "sửa chữa", "bảo hành", "lắp đặt", "liên hệ", "sdt", "số điện thoại", "zalo", "sửa"]

@router.post("")
def chat_bot_endpoint(payload: ChatRequest):
    user_msg = payload.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Tin nhắn không được để trống")
    
    msg_lower = user_msg.lower()

    # 1. Nhận diện nhu cầu MUA HÀNG / BÁO GIÁ
    if any(kw in msg_lower for kw in SALES_KEYWORDS):
        reply = (
            "Dạ, để nhận báo giá tốt nhất và tư vấn đặt mua máy in, bạn vui lòng liên hệ bộ phận Bán hàng Đại Thành qua Zalo/SĐT:\n\n"
            "• **Tư vấn bán hàng 01:** [0908 762 316](https://zalo.me/0908762316)\n"
            "• **Tư vấn bán hàng 02:** [0902 724 806](https://zalo.me/0902724806)"
        )
        return {"success": True, "reply": reply}

    # 2. Nhận diện nhu cầu HỖ TRỢ KỸ THUẬT / BẢO HÀNH
    if any(kw in msg_lower for kw in TECH_KEYWORDS) and ("sdt" in msg_lower or "sửa" in msg_lower or "gặp" in msg_lower or "liên hệ" in msg_lower or "zalo" in msg_lower or "bảo hành" in msg_lower):
        reply = (
            "Dạ, bạn có thể kết nối trực tiếp với Đội ngũ Kỹ thuật Đại Thành qua Zalo/SĐT để được hỗ trợ trực tuyến:\n\n"
            "• **Kỹ thuật Lắp đặt:** [0795 570 380](https://zalo.me/0795570380)\n"
            "• **Sửa chữa & Bảo hành:** [0795 570 381](https://zalo.me/0795570381)"
        )
        return {"success": True, "reply": reply}

    # 3. Nếu không phải từ khóa liên hệ -> Tra cứu tài liệu bằng AI như bình thường
    try:
        reply = search_guides_and_answer(user_msg)
        return {"success": True, "reply": reply}
    except Exception as exc:
        return {"success": False, "reply": "Xin lỗi, hệ thống AI đang bận. Vui lòng thử lại sau!"}