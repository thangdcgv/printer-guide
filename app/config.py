import os

from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates
from supabase import create_client, Client
from google import genai

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 1. Kiểm tra biến môi trường trước
if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL chưa được cấu hình trong environment.")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY chưa được cấu hình trong environment.")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY chưa được cấu hình trong environment.")

# 2. Khởi tạo các SDK dịch vụ sau khi chắc chắn đã có đủ Key
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

ai_client = genai.Client(api_key=GEMINI_API_KEY)
# Jinja2 Templates
templates = Jinja2Templates(directory="app/templates")