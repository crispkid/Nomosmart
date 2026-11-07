"""Read-only compatibility for historical page-image receipt artifacts."""
KEY = "ocr_image_checkpoint"

def checkpoint(payload):
    if not isinstance(payload, dict):
        return {}
    value = payload.get(KEY) or (payload.get("execution_snapshot") or {}).get(KEY)
    return value if isinstance(value, dict) and value.get("version") == 1 else {}

