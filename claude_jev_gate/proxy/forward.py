"""转发上游 Anthropic Messages 兼容端点；支持 mock 假响应。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

from ..config import ProxyConfig


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib 默认跟随 3xx 并保留 x-api-key，跨主机重定向会把上游 Key 带给第三方。"""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def mock_messages_response(body: dict[str, Any]) -> dict[str, Any]:
    """可证明的本地假响应（Anthropic messages 形）。"""
    model = str(body.get("model") or "mock-model")
    return {
        "id": f"msg_mock_{uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [
            {
                "type": "text",
                "text": (
                    "[claude-jev-gate upstream mock] "
                    f"echo model={model}; messages={len(body.get('messages') or [])}"
                ),
            }
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 16},
    }


def forward_messages(
    body: dict[str, Any],
    *,
    cfg: ProxyConfig,
    headers: dict[str, str] | None = None,
    query: str = "",
) -> tuple[int, dict[str, str], bytes]:
    """返回 (status, response_headers, raw_body)。"""
    if cfg.upstream_mock:
        payload = json.dumps(mock_messages_response(body), ensure_ascii=False).encode("utf-8")
        return 200, {"Content-Type": "application/json"}, payload
    if not cfg.upstream_base_url:
        err = json.dumps(
            {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "upstream_not_configured: set CLAUDE_JEV_UPSTREAM_BASE_URL or CLAUDE_JEV_UPSTREAM_MOCK=1",
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        return 503, {"Content-Type": "application/json"}, err

    url = cfg.upstream_base_url.rstrip("/") + "/v1/messages" + (f"?{query}" if query else "")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = headers or {}
    req_headers = {
        "Content-Type": "application/json",
        "anthropic-version": headers.get("anthropic-version") or "2023-06-01",
    }
    if headers.get("anthropic-beta"):
        req_headers["anthropic-beta"] = headers["anthropic-beta"]
    if cfg.upstream_api_key:
        # 代理自带 Key 时不透传客户端凭据：那可能是另一家（如 Anthropic）的 Key／OAuth token
        req_headers["x-api-key"] = cfg.upstream_api_key
    else:
        if headers.get("x-api-key"):
            req_headers["x-api-key"] = headers["x-api-key"]
        # 部分兼容口用 Bearer
        if headers.get("authorization"):
            req_headers["Authorization"] = headers["authorization"]

    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with _OPENER.open(req, timeout=120) as resp:
            raw = resp.read()
            out_headers = {"Content-Type": resp.headers.get("Content-Type") or "application/json"}
            return int(resp.status), out_headers, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else str(exc).encode("utf-8")
        return int(exc.code), {"Content-Type": "application/json"}, raw
    except Exception as exc:  # noqa: BLE001
        err = json.dumps(
            {"type": "error", "error": {"type": "api_error", "message": f"upstream_forward_failed:{type(exc).__name__}"}},
            ensure_ascii=False,
        ).encode("utf-8")
        return 502, {"Content-Type": "application/json"}, err
