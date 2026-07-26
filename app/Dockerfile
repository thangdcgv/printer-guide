FROM python:3.10-slim

WORKDIR /app

# Sao chép và cài đặt các thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn dự án vào container
COPY . .

# Hugging Face yêu cầu mở cổng 7860
EXPOSE 7860

# Khởi chạy ứng dụng FastAPI (file main.py nằm ở thư mục gốc)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]