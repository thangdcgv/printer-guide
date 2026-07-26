from dotenv import load_dotenv
import os

from fastapi.templating import Jinja2Templates

load_dotenv()
templates = Jinja2Templates(directory="app/templates")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")