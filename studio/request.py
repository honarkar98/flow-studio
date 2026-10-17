"""Build an HTTP request without sending it."""

from dataclasses import dataclass, field
from pathlib import Path
import re
from urllib.parse import quote, urlencode

from .expressions import VARIABLE, render


@dataclass
class PreparedRequest:
    method: str
    url: str
    headers: dict
    body: object = None
    content_type: str | None = None
    files: dict = field(default_factory=dict)


def build_request(project, step, variables):
    base = project.get("base_url", "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("URL پایهٔ پروژه معتبر نیست.")
    method = (step.get("method") or "GET").upper()
    path = step.get("path") or ""
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("مسیر endpoint باید با / شروع شود.")

    def path_value(name):
        if name not in variables:
            raise ValueError(f"متغیر {name} مقدار ندارد.")
        value = variables[name]
        if isinstance(value, (dict, list)) or value is None:
            raise ValueError(f"متغیر {name} برای URL باید یک مقدار ساده باشد.")
        return quote(str(value), safe="")

    path = VARIABLE.sub(lambda match: path_value(match.group(1)), path)
    path = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda match: path_value(match.group(1)), path)
    url = base + path
    query = render(step.get("query") or {}, variables)
    if query:
        url += "?" + urlencode(query, doseq=True)
    headers = {str(k): str(v) for k, v in render(step.get("headers") or {}, variables).items()}
    mode = step.get("body_mode") or ("json" if step.get("body") is not None else "none")
    body = render(step.get("body"), variables) if mode != "none" else None
    files = {}
    if mode == "multipart":
        for field_name, file_value in (step.get("files") or {}).items():
            file_path = Path(str(render(file_value, variables))).expanduser()
            if not file_path.is_file():
                raise ValueError(f"فایل {field_name} یافت نشد.")
            files[field_name] = str(file_path)
    elif mode not in ("json", "none"):
        raise ValueError("نوع بدنهٔ درخواست پشتیبانی نمی‌شود.")
    content_type = {"json": "application/json", "multipart": "multipart/form-data"}.get(mode)
    return PreparedRequest(method, url, headers, body, content_type, files)
