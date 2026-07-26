def normalize_text(value: str) -> str:
    """
    Chuẩn hóa chuỗi:
    - Bỏ khoảng trắng đầu/cuối
    - Gộp nhiều khoảng trắng thành 1
    - Chuyển thành IN HOA
    """
    return " ".join(value.split()).upper()