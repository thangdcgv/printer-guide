import re
import logging
from app.config import ai_client
from app.database import supabase

logger = logging.getLogger(__name__)

def get_best_available_model_name() -> str:
    """
    Quét danh sách model từ SDK google-genai mới
    và trả về tên model tối ưu nhất.
    """
    PREFERRED_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-1.5-flash",
        "gemini-flash-latest",
    ]
    
    try:
        # SDK mới: lấy danh sách model từ client.models.list()
        all_models = ai_client.models.list()
        available_names = [m.name.replace("models/", "") for m in all_models if m.name]
        
        for preferred in PREFERRED_MODELS:
            if preferred in available_names:
                logger.info(f"Đã chọn model AI: {preferred}")
                return preferred
                
    except Exception as e:
        logger.error(f"Lỗi khi quét danh sách model: {e}")
    
    # Mặc định an toàn
    return "gemini-2.5-flash"

# Lưu tên model tối ưu
SELECTED_MODEL_NAME = get_best_available_model_name()

def extract_keywords(text: str):
    """Bóc tách từ khóa quan trọng (bỏ từ nối)"""
    stop_words = {"cách", "hướng", "dẫn", "làm", "sao", "để", "cài", "đặt", "cho", "máy", "in", "bị", "lỗi", "như", "thế", "nào"}
    words = re.findall(r'\b\w+\b', text.lower())
    return [w for w in words if w not in stop_words and len(w) > 1]

def search_guides_and_answer(user_query: str) -> str:
    try:
        keywords = extract_keywords(user_query)
        guides = []

        # 1. Tìm kiếm theo các từ khóa trong Supabase
        if keywords:
            or_conditions = ",".join([f"title.ilike.%{kw}%" for kw in keywords])
            res = (
                supabase.table("guide")
                .select("id, title, description")
                .eq("is_active", True)
                .or_(or_conditions)
                .limit(8)
                .execute()
            )
            guides = res.data or []

        # 2. Nếu không thấy bài khớp từ khóa, lấy 5 bài mới nhất
        if not guides:
            res_default = (
                supabase.table("guide")
                .select("id, title, description")
                .eq("is_active", True)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            guides = res_default.data or []

        # 3. Chuẩn bị ngữ cảnh cho AI
        context_text = ""
        for g in guides:
            guide_id = g.get("id")
            link = f"/guide/{guide_id}"
            desc = g.get("description") or "Không có mô tả"
            if len(desc) > 200:
                desc = desc[:200] + "..."
            context_text += f"- ID: {guide_id}\n  Tiêu đề: {g.get('title')}\n  Mô tả: {desc}\n  Link: {link}\n\n"

        # 4. Prompt hướng dẫn AI
        prompt = f"""
Bạn là Trợ lý Kỹ thuật của Máy In Đại Thành.
Dưới đây là DỮ LIỆU CÁC BÀI HƯỚNG DẪN ĐANG CÓ TRÊN HỆ THỐNG:

{context_text}

Câu hỏi của khách hàng: "{user_query}"

Quy tắc trả lời:
1. ĐỌC KỸ danh sách bài viết ở trên. Nếu có bài chứa thông tin hoặc liên quan trực tiếp đến dòng máy / lỗi khách hỏi, hãy khẳng định ĐÃ CÓ BÀI HƯỚNG DẪN.
2. KHÔNG ĐƯỢC tự ý báo "chưa có bài hướng dẫn" nếu danh sách trên đã có bài trùng mã máy hoặc chủ đề tương tự.
3. Chỉ khuyên liên hệ kỹ thuật viên khi danh sách hoàn toàn không chứa bài viết nào phù hợp.

ĐỊNH DẠNG TRẢ VỀ BẮT BUỘC (phải tuân thủ tuyệt đối cấu trúc sau):
- Mở đầu bằng một câu chào ngắn gọn khẳng định đã tìm thấy bài viết.
- Tiêu đề bài viết chỉ lấy nội dung chính, ngắn gọn, không thêm mô tả dài, hãy bỏ đi tên máy in không cần cho vào kết quả
- Liệt kê danh sách bài viết theo đúng thứ tự số, mỗi bài **bắt buộc phải nằm trên một dòng riêng biệt** (xuống dòng rõ ràng bằng ký tự xuống dòng) theo mẫu:
1. [Tên tiêu đề bài viết 1](URL_1)
2. [Tên tiêu đề bài viết 2](URL_2)
3. [Tên tiêu đề bài viết 3](URL_3)
"""

        # 5. Gọi AI qua SDK google-genai mới
        response = ai_client.models.generate_content(
            model=SELECTED_MODEL_NAME,
            contents=prompt,
        )
        return response.text

    except Exception as e:
        logger.error("Lỗi AI Chatbot: %s", e, exc_info=True)
        return "Xin lỗi, hệ thống AI đang gặp sự cố nhỏ. Bạn vui lòng thử lại hoặc gõ từ khóa tìm kiếm trực tiếp trên web nhé!"