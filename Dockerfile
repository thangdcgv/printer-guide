FROM python:3.10-slim

WORKDIR /app

# Sao chép và cài đặt các thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn dự án vào container
COPY . .

# Mở cổng động cho Render (Render truyền cổng qua biến môi trường $PORT, mặc định là 10000)
ENV PORT=10000
EXPOSE 10000

# Khởi chạy ứng dụng FastAPI (Sửa lại "main:app" nếu tên file của bác khác)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]