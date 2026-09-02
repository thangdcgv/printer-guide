from fastapi import APIRouter, HTTPException, Form
from pydantic import BaseModel
from app.services.ai_service import search_guides_and_answer

router = APIRouter(prefix="/api/chat", tags=["AI Chatbot"])

class ChatRequest(BaseModel):
    message: str

@router.post("")
def chat_bot_endpoint(payload: ChatRequest):
    user_msg = payload.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Tin nhắn không được để trống")
    
    reply = search_guides_and_answer(user_msg)
    return {"success": True, "reply": reply}