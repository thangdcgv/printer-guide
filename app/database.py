from supabase import create_client, Client

from app.config import SUPABASE_URL
from app.config import SUPABASE_KEY
from app.config import SUPABASE_SERVICE_ROLE_KEY

# Client 1: Dùng cho Auth công khai (đăng nhập, đăng xuất, lấy session)
supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY # Hoặc SUPABASE_KEY thông thường
)

# Client 2: Dùng ĐỘC LẬP cho các tác vụ Backend Admin (Bypass RLS)
# KHÔNG BAO GIỜ gọi supabase_admin.auth.sign_in_with_password trên client này!
supabase_admin: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)