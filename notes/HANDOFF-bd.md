# HANDOFF · Claude Code × Jev 工具闸（给商务拓展）

- **状态**: READY（mock 证明绿）
- **仓路径**: `/workspace/saas-scout/claude-jev-gate`（本地 git，未 push／未公开）
- **Grok session**: `fb705f48-aa5d-4162-8fb1-6f27d5a6e78e`（标题：Claude Code Jev PermissionRequest tool gate）
  - 开工用 Grok Builder 4.7 high；中途 reasoning 过久未落文件，由执行手 shell 收尾至 prove 绿；session id 保留备查。
- **证明时间**: 2026-09-25（Asia/Shanghai）

## 改了什么

新仓 Claude Code plugin／hooks：

- `.claude-plugin/plugin.json` + `hooks/hooks.json`（事件 **PermissionRequest**）
- `bin/permission_request.py`：stdin → 判 → stdout allow JSON 或空
- `claude_jev_gate/`：config／redact／timeouts（daemon+queue）／jev_client（mock+live）／decide／events
- `scripts/prove_gate.py`：mock 矩阵
- `README.md`／`config.example.env`

## 怎么装

见 README「安装」。box 上可直接：

```bash
# 项目 hooks 指向绝对路径，或将本仓注册为 Claude plugin
python3 /workspace/saas-scout/claude-jev-gate/bin/permission_request.py
```

## 怎么开

```bash
export CLAUDE_JEV_GATE_ENABLED=true
# 评测用 mock：
export CLAUDE_JEV_GATE_MOCK=approve
# 或 live：
# export TYPESAFE_API_KEY=...
# export CLAUDE_JEV_GATE_TYPESAFE_VENV=/workspace/tools/typesafe-venv
```

默认关。关后立即回纯人审。

## 怎么测（商务拓展复测）

```bash
cd /workspace/saas-scout/claude-jev-gate
python3 scripts/prove_gate.py
```

期望：exit 0，`prove_gate: ALL GREEN`。

可选：

```bash
printf '%s' '{"tool_name":"Bash","tool_input":{"command":"echo hi"}}' \
  | CLAUDE_JEV_GATE_ENABLED=true CLAUDE_JEV_GATE_MOCK=approve \
    python3 bin/permission_request.py
```

## 已知限制

- **硬禁第二开关未做**
- 默认关；禁止 session／always；fail-closed 交回人审（本阶段不用 behavior:deny 静默拒绝）
- Live 需 TypeSafe Key；禁 Gateway
- 不上架／不计费／不动老板 Mac

## 不要做

不要 push 公开除非老板另说；不要花新钱；半成品不要交老板（本包已 prove 绿）。
