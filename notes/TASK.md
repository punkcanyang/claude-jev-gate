# TASK · Claude Code × Jev 工具闸／自动同意

## Session
- 工具: Grok Builder 4.7（禁止 Fast；default_reasoning_effort=high）
- session id: `fb705f48-aa5d-4162-8fb1-6f27d5a6e78e`
- 标题: Claude Code × Jev 工具闸
- 状态: READY（prove 绿；Grok session 保留，shell 收尾）

## 目标
新仓 `/workspace/saas-scout/claude-jev-gate`：Claude Code **plugin／hooks**，只做 Jev 工具闸／自动同意。
**不要** fork hermes-jev-router；不做模型路由、不做 trim／compress。

## 规格（验收见开工卡）
开工卡：`/workspace/bd-punkcan/开工卡-Claude-Code-Jev工具闸-2026-09-25.md`

要点：
1. PermissionRequest 优先：即将弹权限窗时问 Jev；高置信 approve → `decision.behavior: allow`（只这一次，不写 always／session／updatedPermissions／applyRules）
2. 其余（deny／unsure／低置信／畸形／超时／异常）→ **交回人审**：stdout 空 + exit 0（让 Claude Code 照常问人）。本阶段**不要**用 behavior:deny 静默拒绝（除非能证明安全；开工卡说 fail-closed 交回人审）
3. 默认关：`CLAUDE_JEV_GATE_ENABLED=false`（缺省＝关）
4. 置信门槛默认 0.80；禁 Gateway；TypeSafe 直连 `TYPESAFE_API_KEY`
5. 禁止 session／always 缓存；每次独立问 Jev
6. 脱敏＋截断 tool 名／参数摘要；日志 digest／decision／confidence／latency；无密钥／完整命令
7. 第二开关硬禁：本阶段可不做，README 写「未做」
8. mock 证明脚本 $0：approve／deny／unsure／low_confidence／timeout／error／malformed／disabled；失败非 0

## Claude Code 输出格式（本机 2.1.278 证实事件名 PermissionRequest）
代 allow 一次时 stdout：
```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
```
交回人审：exit 0 且不输出 decision（或空 stdout）。

hooks 配置示例（plugin `hooks/hooks.json` 或项目 settings）：
```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/bin/permission_request.py"
          }
        ]
      }
    ]
  }
}
```
stdin：Claude Code 注入的 PermissionRequest JSON（含 tool_name／tool_input 等）。

## 建议布局
```
claude-jev-gate/
  .claude-plugin/plugin.json
  hooks/hooks.json
  bin/permission_request.py   # CLI entry：读 stdin → 判 → 打 stdout
  claude_jev_gate/
    __init__.py
    config.py
    redact.py
    jev_client.py             # mock + live TypeSafe；超时用 daemon+queue（勿 with ThreadPoolExecutor）
    decide.py                 # 核心：enabled？→ ask → allow once or passthrough
    events.py                 # ~/.claude/claude-jev-gate/events.jsonl 或仓内可配
  scripts/prove_gate.py       # mock 矩阵，失败 exit≠0
  README.md
  notes/HANDOFF-bd.md
  config.example.env
```

## TypeSafe
借鉴 hermes（行为，不拷贝仓）：Choice approve|deny|unsure + confidence。
Live 路径可用本机已有 typesafe SDK（查 `python -c "import typesafe_sdk"` 或 hermes 的 `_ensure_typesafe_path` 思路），禁止 Vercel AI Gateway。

## 验收命令（做完必须跑绿）
```bash
cd /workspace/saas-scout/claude-jev-gate
python3 scripts/prove_gate.py
```

## 不做
fork hermes、模型路由、trim/compress、上架、代持买家 Key、默认开、YOLO 全跳过。

做完写 notes/HANDOFF-bd.md：怎么装、怎么开、怎么测、已知限制。半成品别停。
