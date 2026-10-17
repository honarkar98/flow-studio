"""urllib transport; non-2xx HTTP responses remain ordinary results."""

from dataclasses import dataclass
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass
class HTTPResult:
    status: int
    headers: dict
    body: object
    duration_ms: int


def _decode(raw, headers):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        if "text/" in headers.get("Content-Type", ""):
            return raw.decode("utf-8", errors="replace")
        return {"binary_bytes": len(raw), "content_type": headers.get("Content-Type", "")}


class UrllibTransport:
    def __init__(self, timeout=30):
        self.timeout = timeout

    def send(self, request):
        headers = dict(request.headers)
        data = None
        if request.files:
            boundary = uuid4().hex
            chunks = []
            for key, value in (request.body or {}).items():
                chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
            for key, filename in request.files.items():
                path = Path(filename)
                chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
                              + path.read_bytes() + b"\r\n")
            data = b"".join(chunks) + f"--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif request.body is not None:
            data = json.dumps(request.body, ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        start = time.monotonic()
        prepared = Request(request.url, data=data, headers=headers, method=request.method)
        try:
            with urlopen(prepared, timeout=self.timeout) as response:
                raw = response.read()
                response_headers = dict(response.headers)
                return HTTPResult(response.status, response_headers, _decode(raw, response_headers),
                                  int((time.monotonic() - start) * 1000))
        except HTTPError as error:
            raw = error.read()
            response_headers = dict(error.headers)
            return HTTPResult(error.code, response_headers, _decode(raw, response_headers),
                              int((time.monotonic() - start) * 1000))
