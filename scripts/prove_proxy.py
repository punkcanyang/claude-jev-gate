#!/usr/bin/env python3
"""$0 自检：代理 HTTP 层（透明转发／凭据／跨站防护／fail-open／tool 配对）。本地假上游，失败 exit≠0。"""
from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claude_jev_gate.config import ProxyConfig, RouteConfig, TrimCompressConfig  # noqa: E402
from claude_jev_gate.proxy.server import make_server  # noqa: E402

RESULTS: list[dict] = []
CAPTURED: list[dict] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:240]})
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


class FakeUpstream(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        CAPTURED.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": None})
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/redirect"):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(302)
            self.send_header("Location", "/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        CAPTURED.append(
            {
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": json.loads(self.rfile.read(n) or b"{}"),
            }
        )
        out = b'{"type":"message","role":"assistant","content":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def start(server: ThreadingHTTPServer) -> int:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def post(port: int, body: object, headers: dict[str, str], path: str = "/v1/messages") -> tuple[int, bytes]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    conn.request("POST", path, body=raw, headers={"Host": f"127.0.0.1:{port}", **headers})
    resp = conn.getresponse()
    return resp.status, resp.read()


def orphan_tool_ids(messages: list[dict]) -> list[str]:
    def ids(m: dict | None, kind: str, key: str) -> set:
        c = (m or {}).get("content")
        return {b.get(key) for b in c if isinstance(b, dict) and b.get("type") == kind} if isinstance(c, list) else set()

    bad: list[str] = []
    for i, m in enumerate(messages):
        c = m.get("content")
        if not isinstance(c, list):
            continue
        if m.get("role") == "user":
            prev = messages[i - 1] if i and messages[i - 1].get("role") == "assistant" else None
            ok = ids(prev, "tool_use", "id")
            bad += [b["tool_use_id"] for b in c if b.get("type") == "tool_result" and b["tool_use_id"] not in ok]
        elif m.get("role") == "assistant" and i < len(messages) - 1:
            nxt = messages[i + 1] if messages[i + 1].get("role") == "user" else None
            ok = ids(nxt, "tool_result", "tool_use_id")
            bad += [b["id"] for b in c if b.get("type") == "tool_use" and b["id"] not in ok]
    return bad


def agentic_body() -> dict:
    msgs: list[dict] = [{"role": "user", "content": "please fix the failing test"}]
    for i in range(10):
        msgs.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": f"step {i}"},
                    {"type": "tool_use", "id": f"toolu_{i}", "name": "Bash", "input": {"command": "pytest -q"}},
                ],
            }
        )
        msgs.append(
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"toolu_{i}", "content": "1 failed"}]}
        )
    return {
        "model": "claude-sonnet-4-5",
        "max_tokens": 64,
        "system": [{"type": "text", "text": "You are Claude Code.", "cache_control": {"type": "ephemeral"}}],
        "messages": msgs,
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="claude-jev-gate-prove-proxy-"))
    events = tmp / "events.jsonl"
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    up_url = f"http://127.0.0.1:{start(upstream)}"

    route_off = RouteConfig(
        enabled=False, min_confidence=0.55, timeout_seconds=2.0, mock="heuristic", jev_model="jev-latest",
        primary_model="primary-model", models={k: "primary-model" for k in ("cheap", "primary", "complex", "tool_heavy", "long_context")},
        events_path=events,
    )
    tc_off = TrimCompressConfig(enabled=False, keep_last_n_turns=6, drop_old_tool_noise=True, events_path=events)
    base = ProxyConfig(
        host="127.0.0.1", port=0, upstream_base_url=up_url, upstream_api_key="",
        upstream_mock=False, route=route_off, trim_compress=tc_off,
    )
    json_h = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    body = agentic_body()

    # 1) all switches off → transparent: body, anthropic-beta, query, client creds
    port = start(make_server(base))
    CAPTURED.clear()
    st, _ = post(
        port, body,
        {**json_h, "x-api-key": "client-key", "Authorization": "Bearer client-tok", "anthropic-beta": "beta-x"},
        path="/v1/messages?beta=true",
    )
    got = CAPTURED[0] if CAPTURED else {}
    check("off_transparent_status", st == 200, st)
    check("off_transparent_body", got.get("body") == body, "body changed")
    check("off_forwards_query", got.get("path") == "/v1/messages?beta=true", got.get("path"))
    check("off_forwards_anthropic_beta", got.get("headers", {}).get("anthropic-beta") == "beta-x", got.get("headers"))
    check(
        "no_proxy_key_passes_client_creds",
        got.get("headers", {}).get("x-api-key") == "client-key"
        and got.get("headers", {}).get("authorization") == "Bearer client-tok",
        got.get("headers"),
    )

    # 2) proxy key set → client credentials never reach upstream
    port = start(make_server(replace(base, upstream_api_key="proxy-key")))
    CAPTURED.clear()
    post(port, body, {**json_h, "x-api-key": "client-key", "Authorization": "Bearer client-tok"})
    h = CAPTURED[0]["headers"] if CAPTURED else {}
    check("proxy_key_used", h.get("x-api-key") == "proxy-key", h)
    check("proxy_key_drops_client_authorization", "authorization" not in h, h)

    # 2b) upstream redirect is not followed (would re-send the proxy key to the Location)
    port = start(make_server(replace(base, upstream_base_url=up_url + "/redirect", upstream_api_key="proxy-key")))
    CAPTURED.clear()
    st, _ = post(port, body, json_h)
    check("upstream_redirect_not_followed", st == 302 and not CAPTURED, (st, CAPTURED[:1]))

    # 3) browser-style abuse is rejected before reaching upstream
    port = start(make_server(replace(base, upstream_api_key="proxy-key")))
    CAPTURED.clear()
    st_host, _ = post(port, body, {**json_h, "Host": "evil.example:8787"})
    st_ctype, _ = post(port, json.dumps(body).encode(), {"Content-Type": "text/plain"})
    st_bad, _ = post(port, b"not json", json_h)
    check("rebinding_host_rejected", st_host == 403, st_host)
    check("text_plain_rejected", st_ctype == 415, st_ctype)
    check("invalid_json_rejected", st_bad == 400, st_bad)
    check("rejected_requests_not_forwarded", not CAPTURED, len(CAPTURED))

    # 4) no upstream + mock off → explicit error, not a fake 200
    port = start(make_server(replace(base, upstream_base_url="")))
    st, raw = post(port, body, json_h)
    check("no_upstream_is_503", st == 503 and b"upstream_not_configured" in raw, (st, raw[:80]))

    # 5) trim→compress on: forwarded messages keep valid tool pairs, shorter than input
    tc_on = replace(tc_off, enabled=True)
    port = start(make_server(replace(base, trim_compress=tc_on)))
    CAPTURED.clear()
    st, _ = post(port, body, json_h)
    fwd = CAPTURED[0]["body"]["messages"] if CAPTURED else []
    check("trim_compress_status", st == 200, st)
    check("trim_compress_shorter", 0 < len(fwd) < len(body["messages"]), len(fwd))
    check("trim_compress_no_orphan_tools", not orphan_tool_ids(fwd), orphan_tool_ids(fwd))

    # 6) unwritable events path + route & trim on → still forwarded (fail-open)
    bad_events = Path("/proc/claude-jev-gate-nope/events.jsonl")
    route_on = replace(route_off, enabled=True, events_path=bad_events)
    port = start(
        make_server(replace(base, route=route_on, trim_compress=replace(tc_on, events_path=bad_events)))
    )
    CAPTURED.clear()
    st, _ = post(port, body, json_h)
    check("unwritable_events_fail_open", st == 200 and len(CAPTURED) == 1, st)

    failed = [r for r in RESULTS if not r["ok"]]
    print("---")
    print(f"passed={len(RESULTS) - len(failed)} failed={len(failed)} total={len(RESULTS)}")
    if failed:
        for r in failed:
            print(f"  FAIL {r['name']}: {r['detail']}")
        return 1
    print("prove_proxy: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
