def validate_printer(brand: str, model: str):

    errors = {}

    if not brand:
        errors["brand"] = "Hãng máy không được để trống."

    if not model:
        errors["model"] = "Model không được để trống."

    return errors