from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HttpError(RuntimeError):
    pass


@dataclass(slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str]

    def text(self) -> str:
        charset = "utf-8"
        content_type = self.headers.get("content-type", "")
        if "charset=" in content_type:
            charset = content_type.rsplit("charset=", 1)[-1].split(";", 1)[0].strip()
        return self.body.decode(charset, errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def _sync_request(
    url: str,
    method: str,
    body: bytes | None,
    headers: dict[str, str],
    timeout: int,
) -> HttpResponse:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.status),
                body=response.read(),
                headers={key.lower(): value for key, value in response.headers.items()},
            )
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise HttpError(f"HTTP {exc.code}: {payload[:500]}") from exc
    except URLError as exc:
        raise HttpError(str(exc.reason)) from exc


async def request(
    url: str,
    *,
    method: str = "GET",
    form: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> HttpResponse:
    final_headers = {"User-Agent": "Mozilla/5.0 (compatible; SOLOISTProductAgent/0.1)"}
    final_headers.update(headers or {})
    body: bytes | None = raw_body
    if form is not None:
        if raw_body is not None:
            raise ValueError("form and raw_body are mutually exclusive")
        body = urlencode(form).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        if raw_body is not None:
            raise ValueError("json_body and raw_body are mutually exclusive")
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json")
    return await asyncio.to_thread(_sync_request, url, method, body, final_headers, timeout)
