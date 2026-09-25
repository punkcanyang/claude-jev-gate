"""Anthropic Messages 兼容小 HTTP 服务：路由＋裁压＋转发。"""
from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from ..config import ProxyConfig, load_proxy_config
from ..events import emit
from ..pipeline import apply_trim_then_compress
from ..routing import route_messages_request
from .forward import forward_messages


def _normalize_messages_for_pipeline(body: dict[str, Any]) -> list[dict[str, Any]]:
    """把 Anthropic system + messages 合成 trim/compress 可吃的 list。"""
    out: list[dict[str, Any]] = []
    system = body.get("system")
    if isinstance(system, str) and system.strip():
        out.append({"role": "system", "content": system})
    elif isinstance(system, list):
        texts = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                texts.append(block)
        if texts:
            out.append({"role": "system", "content": "\n".join(texts)})
    messages = body.get("messages")
    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict):
                out.append(dict(m))
    return out


def _apply_pipeline_to_body(body: dict[str, Any], cfg: ProxyConfig) -> dict[str, Any]:
    if not cfg.trim_compress.enabled:
        return body
    combined = _normalize_messages_for_pipeline(body)
    new_msgs, pipeline = apply_trim_then_compress(combined, cfg=cfg.trim_compress)
    emit(
        cfg.trim_compress.events_path,
        "proxy_trim_compress",
        pipeline=pipeline,
        messages_in=len(combined),
        messages_out=len(new_msgs),
    )
    system_msgs = [m for m in new_msgs if m.get("role") == "system"]
    rest = [m for m in new_msgs if m.get("role") != "system"]
    out = dict(body)
    if system_msgs:
        # 合并回 Anthropic system 字段（字符串）
        out["system"] = "\n\n".join(str(m.get("content") or "") for m in system_msgs)
    elif "system" in out:
        # 若原有 system 被裁掉则删除
        out.pop("system", None)
    out["messages"] = rest
    return out


def process_messages_body(body: dict[str, Any], cfg: ProxyConfig) -> dict[str, Any]:
    """应用裁压（若开）再路由改 model（若开）；全关则原样。"""
    out = _apply_pipeline_to_body(body, cfg)
    if cfg.route.enabled:
        decision = route_messages_request(out, cfg=cfg.route)
        model = decision.get("model")
        if model:
            out = dict(out)
            out["model"] = model
            out["_jev_route"] = {
                "label": decision.get("label"),
                "fallback": decision.get("fallback"),
                "reason": decision.get("reason"),
                "confidence": decision.get("confidence"),
            }
    # 上游不需要内部字段
    if "_jev_route" in out:
        # 保留在事件里已记；转发前剥掉
        cleaned = {k: v for k, v in out.items() if k != "_jev_route"}
        return cleaned
    return out


class ProxyHandler(BaseHTTPRequestHandler):
    cfg: ProxyConfig = None  # type: ignore[assignment]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # 安静一点；关键事件走 events.jsonl
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/healthz", "/health", "/"):
            payload = json.dumps(
                {
                    "ok": True,
                    "service": "claude-jev-gate-proxy",
                    "route_enabled": self.cfg.route.enabled,
                    "trim_compress_enabled": self.cfg.trim_compress.enabled,
                    "upstream_mock": self.cfg.upstream_mock or not self.cfg.upstream_base_url,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(200, {"Content-Type": "application/json"}, payload)
            return
        self._send(404, {"Content-Type": "application/json"}, b'{"error":"not_found"}')

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/v1/messages", "/messages"):
            self._send(404, {"Content-Type": "application/json"}, b'{"error":"not_found"}')
            return
        try:
            body = self._read_json()
            processed = process_messages_body(body, self.cfg)
            # 收集客户端头（小写）
            client_headers = {k.lower(): v for k, v in self.headers.items()}
            status, resp_headers, raw = forward_messages(
                processed, cfg=self.cfg, headers=client_headers
            )
            self._send(status, resp_headers, raw)
        except Exception as exc:  # noqa: BLE001
            err = json.dumps(
                {
                    "type": "error",
                    "error": {
                        "type": "proxy_error",
                        "message": f"{type(exc).__name__}:{exc}",
                        "trace": traceback.format_exc()[-500:],
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(500, {"Content-Type": "application/json"}, err)


def make_server(cfg: ProxyConfig | None = None) -> ThreadingHTTPServer:
    cfg = cfg or load_proxy_config()
    ProxyHandler.cfg = cfg
    server = ThreadingHTTPServer((cfg.host, cfg.port), ProxyHandler)
    return server


def serve_forever(cfg: ProxyConfig | None = None) -> None:
    cfg = cfg or load_proxy_config()
    server = make_server(cfg)
    print(
        f"claude-jev-gate proxy listening on http://{cfg.host}:{cfg.port} "
        f"(route={cfg.route.enabled} trim_compress={cfg.trim_compress.enabled} "
        f"upstream_mock={cfg.upstream_mock or not cfg.upstream_base_url})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down", flush=True)
        server.shutdown()
