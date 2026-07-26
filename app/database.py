from supabase import create_client

from app.config import SUPABASE_URL
from app.config import SUPABASE_KEY

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)