"""Safe Swagger/OpenAPI catalogue import."""

import yaml

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
MAX_SCHEMA_BYTES = 10 * 1024 * 1024


def parse(text):
    """Return (version, operation dictionaries) from Swagger 2 or OpenAPI 3."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise ValueError("فایل Swagger خالی یا بیش از ۱۰ مگابایت است.")
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError("ساختار YAML/JSON معتبر نیست.") from exc
    if not isinstance(document, dict):
        raise ValueError("ریشهٔ Swagger باید یک شیء باشد.")
    version = document.get("openapi") or document.get("swagger")
    if not isinstance(version, str) or not (version.startswith("3.") or version == "2.0"):
        raise ValueError("تنها Swagger 2.0 و OpenAPI 3.x پشتیبانی می‌شوند.")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("بخش paths در Swagger وجود ندارد.")
    operations = []
    for path, methods in paths.items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(methods, dict):
            raise ValueError("مسیر endpoint معتبر نیست.")
        for method, operation in methods.items():
            if str(method).lower() not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                raise ValueError(f"تعریف {method} {path} معتبر نیست.")
            operations.append({
                "method": method.upper(),
                "path": path,
                "operation_id": operation.get("operationId") or "",
                "summary": operation.get("summary") or operation.get("description") or "",
                "details": operation,
            })
    return version, operations
