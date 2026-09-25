# DOGFOOD · Live DeepSeek via claude-jev-gate Anthropic proxy

- **Time**: 2026-09-25 20:20:02 CST (Asia/Shanghai)
- **Commit area**: e66dd2e (local; not pushed)
- **Result**: **PASS** — live upstream (not mock)

## Env switches used

| Switch | Value |
|--------|-------|
| `CLAUDE_JEV_UPSTREAM_MOCK` | `0` |
| `CLAUDE_JEV_UPSTREAM_BASE_URL` | `https://api.deepseek.com/anthropic` |
| `CLAUDE_JEV_UPSTREAM_API_KEY` | from `~/.hermes/.env` `DEEPSEEK_API_KEY` (not logged) |
| `CLAUDE_JEV_ROUTE_ENABLED` | `true` |
| `CLAUDE_JEV_TRIM_COMPRESS_ENABLED` | `true` |
| `CLAUDE_JEV_ROUTE_MOCK` | **unset** (live TypeSafe/Jev; `TYPESAFE_API_KEY` present) |
| `CLAUDE_JEV_PRIMARY_MODEL` | `deepseek-chat` |
| `CLAUDE_JEV_GATE_ENABLED` | left alone (hooks separate) |
| Proxy listen | `http://127.0.0.1:8787` |
| Python | `/workspace/tools/typesafe-venv/bin/python bin/proxy_server.py` |

## healthz

`GET http://127.0.0.1:8787/healthz` → **OK**

```json
{
  "ok": true,
  "service": "claude-jev-gate-proxy",
  "route_enabled": true,
  "trim_compress_enabled": true,
  "upstream_mock": false
}
```

## curl (live)

`POST /v1/messages` with tiny prompt `Reply with exactly: PROXY_LIVE_OK`; client `x-api-key: dogfood-client` (proxy uses upstream key from env).

- **HTTP**: **200**
- **Reply excerpt**: `PROXY_LIVE_OK`
- **Upstream model id in body**: `deepseek-v4-flash`
- **stop_reason**: `end_turn`
- **usage** (approx): input_tokens=13, output_tokens=5
- Looks **live** (not transparent offline mock): real model id + exact phrase + non-mock healthz.

## Claude CLI

- Binary: `~/.local/bin/claude` present
- `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`, `ANTHROPIC_API_KEY` = DeepSeek key (not logged)
- Command: `claude -p "Reply with exactly: PROXY_LIVE_OK" --model deepseek-chat --bare --output-format text`
- **Exit**: 0
- **Stdout**: `PROXY_LIVE_OK`
- **Note**: CLI warned that `deepseek-chat` is not in its model catalog / unrecognized_model; still completed successfully via proxy.
- **Claude CLI path**: **worked** (not curl-only)

## Routing / trim evidence (`~/.claude/claude-jev-gate/events.jsonl`)

For the live curl (~20:19 CST):

1. `trim` order=1 (short msg; chars unchanged)
2. `compress` order=2, `stub: true`, `skipped_short: true`
3. `trim_then_compress_pipeline` with `order_ok: true`
4. `proxy_trim_compress`
5. `route_decision`: `backend: typesafe`, `reason: jev_choice`, `jev_model: jev-1.13.0`, label `cheap` → `deepseek-chat`, confidence ~0.93

Claude CLI turn (~20:19:51 CST) similarly logged `route_decision` with live TypeSafe `jev_choice`.

Compress remains local heuristic stub (as designed); pipeline order proven.

## Cleanup

Background proxy PID stopped after dogfood.

## Failures / blockers

None for this live path.
