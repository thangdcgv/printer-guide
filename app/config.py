import os

from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates


load_dotenv()


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL chưa được cấu hình trong environment."
    )

if not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_KEY chưa được cấu hình trong environment."
    )


templates = Jinja2Templates(
    directory="app/templates"
)
