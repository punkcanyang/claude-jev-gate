"""Anthropic Messages 兼容小 HTTP 服务：路由＋裁压＋转发。"""
from __future__ import annotations

import hmac
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from ..config import ProxyConfig, load_proxy_config
from ..events import emit
from ..pipeline import apply_trim_then_compress
from ..routing import route_messages_request
from .forward import forward_messages, iter_forward_messages


def _normalize_messages_for_pipeline(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """把 Anthropic system + messages 合成 trim/compress 可吃的 list。

    P2-5：若 system 是带 cache_control 的数组，保留原始数组形态元数据，回写时尽量还原。
    返回 (combined_messages, system_meta)。
    system_meta = {"kind":"string"|"blocks", "value": ...} 或 None。
    """
    out: list[dict[str, Any]] = []
    system_meta: dict[str, Any] | None = None
    system = body.get("system")
    if isinstance(system, str) and system.strip():
        out.append({"role": "system", "content": system})
        system_meta = {"kind": "string", "value": system}
    elif isinstance(system, list):
        # 保留 blocks（含 cache_control）供回写
        system_meta = {"kind": "blocks", "value": [dict(b) if isinstance(b, dict) else b for b in system]}
        texts = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                texts.append(block)
        if texts:
            # pipeline 内部仍用合并字符串作 system 角色；回写时优先还原 blocks
            out.append({"role": "system", "content": "\n".join(texts), "_orig_system_blocks": True})
    messages = body.get("messages")
    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict):
                out.append(dict(m))
    return out, system_meta


def _block_ids(message: dict[str, Any] | None, block_type: str, key: str) -> set[Any]:
    content = (message or {}).get("content")
    if not isinstance(content, list):
        return set()
    return {b.get(key) for b in content if isinstance(b, dict) and b.get("type") == block_type}


def repair_tool_pairs(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉被裁断的 tool_use／tool_result。

    Anthropic 要求每个 tool_result 对应紧邻上一条 assistant 的 tool_use，
    且非末尾 assistant 的每个 tool_use 在紧邻下一条 user 里有 tool_result；否则 400。
    """
    msgs = list(messages)
    while True:
        changed = False
        out: list[dict[str, Any]] = []
        for i, m in enumerate(msgs):
            content = m.get("content")
            role = m.get("role")
            if not isinstance(content, list):
                out.append(m)
                continue
            if role == "user":
                prev = msgs[i - 1] if i > 0 and msgs[i - 1].get("role") == "assistant" else None
                valid = _block_ids(prev, "tool_use", "id")
                keep = [
                    b for b in content
                    if not (isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") not in valid)
                ]
            elif role == "assistant" and i < len(msgs) - 1:
                nxt = msgs[i + 1] if msgs[i + 1].get("role") == "user" else None
                valid = _block_ids(nxt, "tool_result", "tool_use_id")
                keep = [
                    b for b in content
                    if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") not in valid)
                ]
            else:
                keep = content
            if len(keep) != len(content):
                changed = True
                if not keep:
                    continue
                m = {**m, "content": keep}
            out.append(m)
        msgs = out
        if not changed:
            return msgs


def _restore_system(out: dict[str, Any], system_msgs: list[dict[str, Any]], system_meta: dict[str, Any] | None) -> None:
    """P2-5：尽量保留原 system 数组的 cache_control。"""
    if not system_msgs:
        out.pop("system", None)
        return
    # 裁压未改动 system 文本且原为 blocks → 原样回写（保留 cache_control）
    if system_meta and system_meta.get("kind") == "blocks":
        orig_blocks = system_meta.get("value") or []
        orig_text = "\n".join(
            str(b.get("text") or "") if isinstance(b, dict) else str(b) for b in orig_blocks
        )
        new_text = "\n\n".join(str(m.get("content") or "") for m in system_msgs)
        # 文本未变 → 保留原 blocks（含 cache_control）
        if orig_text.strip() == new_text.strip() or "\n".join(
            str(m.get("content") or "") for m in system_msgs
        ).strip() == orig_text.strip():
            out["system"] = orig_blocks
            return
        # 文本变了：尽量在第一个 text block 上更新 text，保留 cache_control
        new_blocks: list[Any] = []
        replaced = False
        for b in orig_blocks:
            if isinstance(b, dict) and b.get("type") == "text" and not replaced:
                nb = dict(b)
                nb["text"] = new_text
                new_blocks.append(nb)
                replaced = True
            elif isinstance(b, dict) and b.get("type") == "text" and replaced:
                continue  # 合并进第一个
            else:
                new_blocks.append(b)
        if not replaced:
            block: dict[str, Any] = {"type": "text", "text": new_text}
            # 若原有任一 cache_control，挂到新 block
            for b in orig_blocks:
                if isinstance(b, dict) and b.get("cache_control"):
                    block["cache_control"] = b["cache_control"]
                    break
            new_blocks = [block]
        out["system"] = new_blocks
        return
    out["system"] = "\n\n".join(str(m.get("content") or "") for m in system_msgs)


def _apply_pipeline_to_body(body: dict[str, Any], cfg: ProxyConfig) -> dict[str, Any]:
    if not cfg.trim_compress.enabled:
        return body
    combined, system_meta = _normalize_messages_for_pipeline(body)
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
    _restore_system(out, system_msgs, system_meta)
    out["messages"] = repair_tool_pairs(rest)
    return out


def process_messages_body(body: dict[str, Any], cfg: ProxyConfig) -> dict[str, Any]:
    """应用裁压（若开）再路由改 model（若开）；全关则原样。两者出错都 fail-open，不堵对话。

    P2-3：路由异常／fail-open 用客户端 model，禁止无条件塞 deepseek-chat。
    """
    client_model = str(body.get("model") or "").strip() or None
    try:
        out = _apply_pipeline_to_body(body, cfg)
    except Exception as exc:  # noqa: BLE001
        emit(cfg.trim_compress.events_path, "proxy_trim_compress_error", error_class=type(exc).__name__)
        out = body
    if cfg.route.enabled:
        try:
            decision = route_messages_request(out, cfg=cfg.route)
        except Exception as exc:  # noqa: BLE001
            decision = {
                "model": client_model or cfg.route.primary_model,
                "label": "primary",
                "fallback": True,
                "reason": f"route_error:{type(exc).__name__}",
            }
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
        cleaned = {k: v for k, v in out.items() if k != "_jev_route"}
        return cleaned
    return out


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _host_without_port(host_header: str) -> str:
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1:].split("]", 1)[0]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


class ProxyHandler(BaseHTTPRequestHandler):
    cfg: ProxyConfig = None  # type: ignore[assignment]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # 安静一点；关键事件走 events.jsonl
        return

    def _host_allowed(self) -> bool:
        """挡 DNS rebinding：浏览器发来的 Host 是攻击者域名。代理会注入上游 Key，不能被网页当跳板。"""
        allowed = set(_LOOPBACK_HOSTS)
        if self.cfg.host not in ("", "0.0.0.0", "::"):
            allowed.add(self.cfg.host.lower())
        return _host_without_port(self.headers.get("Host") or "") in allowed

    def _auth_ok(self) -> bool:
        """P2-4：可选客户端鉴权。默认关（auth_token 空）；开启后须带专用头。"""
        token = (self.cfg.auth_token or "").strip()
        if not token:
            return True
        got = (self.headers.get("x-claude-jev-proxy-token") or "").strip()
        return bool(got) and hmac.compare_digest(got.encode("utf-8"), token.encode("utf-8"))

    def _read_json(self) -> dict[str, Any] | None | str:
        """成功返回 dict；超限返回 'too_large'；非法返回 None。"""
        length = int(self.headers.get("Content-Length") or 0)
        max_body = int(getattr(self.cfg, "max_body_bytes", 32 * 1024 * 1024) or 32 * 1024 * 1024)
        if length > max_body:
            # 尽量排空以免连接挂住
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            return "too_large"
        raw = self.rfile.read(length) if length > 0 else b""
        if len(raw) > max_body:
            return "too_large"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        return data if isinstance(data, dict) else None

    def _send_error_json(self, status: int, err_type: str, message: str) -> None:
        body = json.dumps(
            {"type": "error", "error": {"type": err_type, "message": message}}, ensure_ascii=False
        ).encode("utf-8")
        self._send(status, {"Content-Type": "application/json"}, body)

    def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_stream(self, status: int, headers: dict[str, str], chunks: Any) -> None:
        """P2-7：边收边写，以关连接结束响应体。

        本服务按 HTTP/1.0 应答，1.0 不允许 Transfer-Encoding: chunked，只能不带长度、写完即关。
        """
        self.close_connection = True
        self.send_response(status)
        for k, v in headers.items():
            if k.lower() in ("content-length", "transfer-encoding", "connection"):
                continue
            self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for chunk in chunks:
                if not chunk:
                    continue
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            close = getattr(chunks, "close", None)
            if callable(close):
                close()

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_allowed():
            self._send_error_json(403, "permission_error", "host_not_allowed")
            return
        if not self._auth_ok():
            self._send_error_json(401, "authentication_error", "proxy_auth_required")
            return
        path = urlparse(self.path).path
        if path in ("/healthz", "/health", "/"):
            payload = json.dumps(
                {
                    "ok": True,
                    "service": "claude-jev-gate-proxy",
                    "route_enabled": self.cfg.route.enabled,
                    "trim_compress_enabled": self.cfg.trim_compress.enabled,
                    "upstream_mock": self.cfg.upstream_mock,
                    "upstream_configured": bool(self.cfg.upstream_base_url),
                    "auth_required": bool(self.cfg.auth_token),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(200, {"Content-Type": "application/json"}, payload)
            return
        self._send(404, {"Content-Type": "application/json"}, b'{"error":"not_found"}')

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_allowed():
            self._send_error_json(403, "permission_error", "host_not_allowed")
            return
        if not self._auth_ok():
            self._send_error_json(401, "authentication_error", "proxy_auth_required")
            return
        parsed = urlparse(self.path)
        path = parsed.path

        # P2-7：count_tokens — 有上游则透传，否则 501
        if path in ("/v1/messages/count_tokens", "/messages/count_tokens"):
            self._handle_count_tokens(parsed)
            return

        if path not in ("/v1/messages", "/messages"):
            self._send(404, {"Content-Type": "application/json"}, b'{"error":"not_found"}')
            return
        # 非 JSON 类型 = 浏览器可免预检跨站发的 simple request；强制 JSON 逼出 CORS 预检（本服务不应答 OPTIONS）
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            self._send_error_json(415, "invalid_request_error", "content_type_must_be_application_json")
            return
        try:
            body = self._read_json()
            if body == "too_large":
                self._send_error_json(413, "invalid_request_error", "body_too_large")
                return
            if body is None:
                self._send_error_json(400, "invalid_request_error", "body_must_be_json_object")
                return
            processed = process_messages_body(body, self.cfg)
            client_headers = {k.lower(): v for k, v in self.headers.items()}
            want_stream = bool(processed.get("stream")) or "text/event-stream" in (
                client_headers.get("accept") or ""
            ).lower()

            if want_stream and not self.cfg.upstream_mock:
                status, resp_headers, chunks = iter_forward_messages(
                    processed, cfg=self.cfg, headers=client_headers, query=parsed.query
                )
                # SSE 上游通常已是 text/event-stream
                self._send_stream(status, resp_headers, chunks)
            else:
                status, resp_headers, raw = forward_messages(
                    processed, cfg=self.cfg, headers=client_headers, query=parsed.query
                )
                self._send(status, resp_headers, raw)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(500, "api_error", f"proxy_error:{type(exc).__name__}")

    def _handle_count_tokens(self, parsed: Any) -> None:
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            self._send_error_json(415, "invalid_request_error", "content_type_must_be_application_json")
            return
        body = self._read_json()
        if body == "too_large":
            self._send_error_json(413, "invalid_request_error", "body_too_large")
            return
        if body is None:
            self._send_error_json(400, "invalid_request_error", "body_must_be_json_object")
            return
        if self.cfg.upstream_mock or not self.cfg.upstream_base_url:
            self._send_error_json(
                501,
                "not_implemented_error",
                "count_tokens_requires_upstream: set CLAUDE_JEV_UPSTREAM_BASE_URL",
            )
            return
        client_headers = {k.lower(): v for k, v in self.headers.items()}
        status, resp_headers, raw = forward_messages(
            body,
            cfg=self.cfg,
            headers=client_headers,
            query=parsed.query,
            path="/v1/messages/count_tokens",
        )
        self._send(status, resp_headers, raw)


def make_server(cfg: ProxyConfig | None = None) -> ThreadingHTTPServer:
    cfg = cfg or load_proxy_config()
    handler = type("BoundProxyHandler", (ProxyHandler,), {"cfg": cfg})
    return ThreadingHTTPServer((cfg.host, cfg.port), handler)


def serve_forever(cfg: ProxyConfig | None = None) -> None:
    cfg = cfg or load_proxy_config()
    server = make_server(cfg)
    if cfg.host not in _LOOPBACK_HOSTS:
        print(
            f"WARNING: proxy bound to non-loopback {cfg.host}; "
            + (
                "client auth is enabled via CLAUDE_JEV_PROXY_AUTH_TOKEN. "
                if cfg.auth_token
                else "it has no client auth and injects the upstream API key for anyone who can reach this port. "
            ),
            file=sys.stderr,
            flush=True,
        )
    print(
        f"claude-jev-gate proxy listening on http://{cfg.host}:{cfg.port} "
        f"(route={cfg.route.enabled} trim_compress={cfg.trim_compress.enabled} "
        f"upstream_mock={cfg.upstream_mock} upstream_configured={bool(cfg.upstream_base_url)} "
        f"auth={'on' if cfg.auth_token else 'off'})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down", flush=True)
        server.shutdown()
