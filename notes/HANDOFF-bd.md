# HANDOFF · Claude Code × 路由＋先裁再压（给商务拓展）

- **状态**: READY（三 prove 绿；代理 mock 演示绿）
- **仓路径**: `/workspace/saas-scout/claude-jev-gate`（本地 git，未 push／未公开）
- **Grok session**: `fb705f48-aa5d-4162-8fb1-6f27d5a6e78e`（同一任务复用）
  - 开工用 Grok Builder 4.7 high；落文件／证明由执行手 shell 收尾；session id 保留备查。
- **证明时间**: 2026-09-25（Asia/Shanghai）

## 改了什么

在已有 **PermissionRequest 工具闸** 上扩展：

1. 本机 **Anthropic Messages 兼容代理**（`bin/proxy_server.py`）→ Claude Code 设 `ANTHROPIC_BASE_URL`
2. **模型路由**（`claude_jev_gate/routing.py`）：Jev／heuristic／mock；fail-open 主模型
3. **先裁再压**（`trim.py` + `compress.py` + `pipeline.py`）：强制 trim→compress；compress 为本地启发式 stub
4. 三开关分开，默认全关：`CLAUDE_JEV_GATE_ENABLED`／`CLAUDE_JEV_ROUTE_ENABLED`／`CLAUDE_JEV_TRIM_COMPRESS_ENABLED`
5. hooks 解释器用 `/workspace/tools/typesafe-venv/bin/python`；`ensure_typesafe_path` **insert(0)**
6. `scripts/prove_routing.py`／`prove_trim_compress.py`／`demo_proxy_curl.sh`；`data/routing_samples.jsonl`（20 条）
7. README／`config.example.env` 更新

工具闸原 `scripts/prove_gate.py` **仍 13/13 绿**。

## 怎么复测（商务拓展）

```bash
cd /workspace/saas-scout/claude-jev-gate

# 1) 三 prove
python3 scripts/prove_gate.py
python3 scripts/prove_routing.py
python3 scripts/prove_trim_compress.py

# 2) 代理演示（mock 上游，无需 Key）
./scripts/demo_proxy_curl.sh

# 3) 可选：真人上游（有 DeepSeek／Anthropic 兼容 Key）
# export CLAUDE_JEV_UPSTREAM_MOCK=0
# export CLAUDE_JEV_UPSTREAM_BASE_URL=https://api.deepseek.com/anthropic
# export CLAUDE_JEV_UPSTREAM_API_KEY=...
# export CLAUDE_JEV_ROUTE_ENABLED=true
# /workspace/tools/typesafe-venv/bin/python bin/proxy_server.py
# 另开终端：export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
```

期望：三 prove exit 0；demo 打印 healthz + mock messages 响应。

## 三开关怎么开

```bash
export CLAUDE_JEV_GATE_ENABLED=true          # 工具闸
export CLAUDE_JEV_ROUTE_ENABLED=true         # 路由
export CLAUDE_JEV_TRIM_COMPRESS_ENABLED=true # 裁压
# 评测 mock：
export CLAUDE_JEV_GATE_MOCK=approve
export CLAUDE_JEV_ROUTE_MOCK=heuristic
export CLAUDE_JEV_UPSTREAM_MOCK=1
```

全关 → 行为可预期回退（不启代理＝直连上游＋原版人审；启代理且路由／裁压关＝透明转发）。

## 已知限制

- compress 是本地 stub（非上游 LLM 压）；顺序有事件／pipeline 证明
- 硬禁第二开关未做；默认关；禁 Gateway；不上架／不计费
- Live Jev 需 `TYPESAFE_API_KEY`；上游 live 需兼容 Key
- 不动老板 Mac；勿 push 公开除非老板另说

## 报告路径

- `notes/reports/routing-prove.md`
- `notes/reports/trim-compress-proof.md`
