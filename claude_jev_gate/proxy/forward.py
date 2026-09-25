"""转发上游 Anthropic Messages 兼容端点；支持 mock 假响应。

P2-7：尽量按块读上游并流式写出；透传 request-id／retry-after／限流头。
非 stream 请求仍整包读回（边界见 README）。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterator
from uuid import uuid4

from ..config import ProxyConfig

# 透传给客户端的有用响应头（大小写不敏感匹配）
_PASSTHROUGH_HEADER_EXACT = frozenset(
    {
        "content-type",
        "request-id",
        "x-request-id",
        "retry-after",
        "anthropic-request-id",
    }
)
_PASSTHROUGH_HEADER_PREFIXES = ("anthropic-ratelimit-", "x-ratelimit-", "ratelimit-")


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


def _collect_passthrough_headers(resp_headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        items = resp_headers.items()
    except Exception:  # noqa: BLE001
        return {"Content-Type": "application/json"}
    for k, v in items:
        lk = str(k).lower()
        if lk in _PASSTHROUGH_HEADER_EXACT or any(lk.startswith(p) for p in _PASSTHROUGH_HEADER_PREFIXES):
            # 保留常见规范写法
            if lk == "content-type":
                out["Content-Type"] = v
            elif lk == "retry-after":
                out["Retry-After"] = v
            else:
                out[k] = v
    if "Content-Type" not in out:
        out["Content-Type"] = "application/json"
    return out


def _build_upstream_request(
    body: dict[str, Any],
    *,
    cfg: ProxyConfig,
    headers: dict[str, str] | None,
    query: str,
    path: str = "/v1/messages",
) -> urllib.request.Request:
    url = cfg.upstream_base_url.rstrip("/") + path + (f"?{query}" if query else "")
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
    return urllib.request.Request(url, data=data, headers=req_headers, method="POST")


def forward_messages(
    body: dict[str, Any],
    *,
    cfg: ProxyConfig,
    headers: dict[str, str] | None = None,
    query: str = "",
    path: str = "/v1/messages",
) -> tuple[int, dict[str, str], bytes]:
    """返回 (status, response_headers, raw_body)。整包读回（非 stream 路径）。"""
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

    req = _build_upstream_request(body, cfg=cfg, headers=headers, query=query, path=path)
    try:
        with _OPENER.open(req, timeout=120) as resp:
            raw = resp.read()
            out_headers = _collect_passthrough_headers(resp.headers)
            return int(resp.status), out_headers, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else str(exc).encode("utf-8")
        out_headers = _collect_passthrough_headers(getattr(exc, "headers", {}) or {})
        return int(exc.code), out_headers, raw
    except Exception as exc:  # noqa: BLE001
        err = json.dumps(
            {"type": "error", "error": {"type": "api_error", "message": f"upstream_forward_failed:{type(exc).__name__}"}},
            ensure_ascii=False,
        ).encode("utf-8")
        return 502, {"Content-Type": "application/json"}, err


def iter_forward_messages(
    body: dict[str, Any],
    *,
    cfg: ProxyConfig,
    headers: dict[str, str] | None = None,
    query: str = "",
    path: str = "/v1/messages",
    chunk_size: int = 65536,
) -> tuple[int, dict[str, str], Iterator[bytes]]:
    """P2-7：尽量流式。返回 (status, headers, chunk_iterator)。

    mock／未配置上游时退化为单块 iterator。调用方负责耗尽 iterator。
    """
    if cfg.upstream_mock or not cfg.upstream_base_url:
        status, hdrs, raw = forward_messages(body, cfg=cfg, headers=headers, query=query, path=path)

        def _one() -> Iterator[bytes]:
            yield raw

        return status, hdrs, _one()

    req = _build_upstream_request(body, cfg=cfg, headers=headers, query=query, path=path)

    def _err_iter(msg: str) -> tuple[int, dict[str, str], Iterator[bytes]]:
        raw = json.dumps(
            {"type": "error", "error": {"type": "api_error", "message": msg}},
            ensure_ascii=False,
        ).encode("utf-8")

        def _one() -> Iterator[bytes]:
            yield raw

        return 502, {"Content-Type": "application/json"}, _one()

    try:
        resp = _OPENER.open(req, timeout=120)
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else str(exc).encode("utf-8")
        out_headers = _collect_passthrough_headers(getattr(exc, "headers", {}) or {})

        def _one() -> Iterator[bytes]:
            yield raw

        return int(exc.code), out_headers, _one()
    except Exception as exc:  # noqa: BLE001
        return _err_iter(f"upstream_forward_failed:{type(exc).__name__}")

    out_headers = _collect_passthrough_headers(resp.headers)
    status = int(resp.status)

    def _chunks() -> Iterator[bytes]:
        try:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

    return status, out_headers, _chunks()
