#!/usr/bin/env bash
# 演示：经本机代理打 Anthropic Messages 形请求（默认上游 mock）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${CLAUDE_JEV_PROXY_HOST:-127.0.0.1}"
PORT="${CLAUDE_JEV_PROXY_PORT:-8787}"
BASE="http://${HOST}:${PORT}"

export CLAUDE_JEV_UPSTREAM_MOCK="${CLAUDE_JEV_UPSTREAM_MOCK:-1}"
export CLAUDE_JEV_ROUTE_ENABLED="${CLAUDE_JEV_ROUTE_ENABLED:-true}"
export CLAUDE_JEV_TRIM_COMPRESS_ENABLED="${CLAUDE_JEV_TRIM_COMPRESS_ENABLED:-true}"
export CLAUDE_JEV_ROUTE_MOCK="${CLAUDE_JEV_ROUTE_MOCK:-heuristic}"
export CLAUDE_JEV_PRIMARY_MODEL="${CLAUDE_JEV_PRIMARY_MODEL:-deepseek-chat}"
export CLAUDE_JEV_MODEL_CHEAP="${CLAUDE_JEV_MODEL_CHEAP:-deepseek-chat}"
export CLAUDE_JEV_MODEL_COMPLEX="${CLAUDE_JEV_MODEL_COMPLEX:-deepseek-reasoner}"

PYTHON="${CLAUDE_JEV_GATE_PYTHON:-/workspace/tools/typesafe-venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON=python3; fi

# 若端口未被占用则后台起代理
if ! curl -sf "${BASE}/healthz" >/dev/null 2>&1; then
  "$PYTHON" "$ROOT/bin/proxy_server.py" >/tmp/claude-jev-gate-proxy.log 2>&1 &
  PROXY_PID=$!
  trap 'kill $PROXY_PID 2>/dev/null || true' EXIT
  for i in $(seq 1 50); do
    curl -sf "${BASE}/healthz" >/dev/null 2>&1 && break
    sleep 0.1
  done
fi

echo "== healthz =="
curl -sS "${BASE}/healthz" | python3 -m json.tool

echo "== POST /v1/messages =="
curl -sS "${BASE}/v1/messages" \
  -H 'content-type: application/json' \
  -H 'x-api-key: mock' \
  -H 'anthropic-version: 2023-06-01' \
  -d '{
    "model": "deepseek-chat",
    "max_tokens": 64,
    "system": "你是助手。",
    "messages": [
      {"role": "user", "content": "现在几点？"},
      {"role": "assistant", "content": "我无法获知实时时间。"},
      {"role": "user", "content": "那翻译 hello"}
    ]
  }' | python3 -m json.tool

echo "demo_proxy_curl: OK"
