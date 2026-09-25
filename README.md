# claude-jev-gate

Claude Code **plugin／hooks**：在 `PermissionRequest` 弹窗前问 TypeSafe **Jev**。  
高置信 `approve` → 代点 **允许这一次**；其余（deny／unsure／低置信／畸形／超时／异常）→ **交回人审**（空 stdout + exit 0）。

默认关。不做模型路由、不做 trim／compress。不 fork `hermes-jev-router`（只借鉴 fail-closed 行为与超时写法）。

## 安装

本仓布局：

```
.claude-plugin/plugin.json
hooks/hooks.json
bin/permission_request.py
claude_jev_gate/
```

任选其一：

1. **Claude Code plugin**：把本仓加为本地 plugin（或 symlink 到 Claude plugins 目录），确保 `hooks/hooks.json` 被加载。Hook 命令使用 `${CLAUDE_PLUGIN_ROOT}`。
2. **项目／用户 settings hooks**：在 `.claude/settings.json`（或用户级）写入与 `hooks/hooks.json` 相同的 `PermissionRequest` command，把路径换成绝对路径，例如：
   `python3 /workspace/saas-scout/claude-jev-gate/bin/permission_request.py`

需要 Python 3.10+。Live 模式另需 `typesafe_sdk`（见下）。

## 开关

| 变量 | 默认 | 含义 |
|------|------|------|
| `CLAUDE_JEV_GATE_ENABLED` | 关 | `true`／`1`／`on` 才启用 |
| `CLAUDE_JEV_GATE_MIN_CONFIDENCE` | `0.80` | approve 代点门槛（有效 floor ≥ 0.5） |
| `CLAUDE_JEV_GATE_TIMEOUT_SECONDS` | `8` | Jev 调用硬超时 |
| `CLAUDE_JEV_GATE_MOCK` | 空 | 本地矩阵：`approve\|deny\|unsure\|low_confidence\|timeout\|error\|malformed` |
| `TYPESAFE_API_KEY` | — | Live 直连 TypeSafe（**禁止** Vercel AI Gateway） |
| `CLAUDE_JEV_GATE_TYPESAFE_VENV` | — | 可选；注入 typesafe_sdk（例：`/workspace/tools/typesafe-venv`） |
| `CLAUDE_JEV_GATE_TYPESAFE_SITE_PACKAGES` | — | 可选；site-packages 路径（`os.pathsep` 多分隔） |
| `CLAUDE_JEV_GATE_EVENTS_PATH` | `~/.claude/claude-jev-gate/events.jsonl` | 事件日志 |

示例见 `config.example.env`。密钥不要进仓。

关开关（或 unset）后行为与原版 Claude Code 人审一致。

## 怎么验

```bash
cd /workspace/saas-scout/claude-jev-gate
python3 scripts/prove_gate.py
```

必须 exit 0。覆盖：disabled、approve→allow、其余交回人审、timeout 及时返回、无 Key fail-closed、日志无密钥样例。

可选抽查：

```bash
printf '%s' '{"tool_name":"Bash","tool_input":{"command":"ls"}}' \
  | CLAUDE_JEV_GATE_ENABLED=true CLAUDE_JEV_GATE_MOCK=approve \
    python3 bin/permission_request.py
# 期望一行 JSON：hookEventName=PermissionRequest, behavior=allow
```

真人 Claude Code：装上 hooks → 保持默认关确认仍会弹窗 → `CLAUDE_JEV_GATE_ENABLED=true` 且设 MOCK 或 Key → 安全命令应被代点一次（无 always）。

## 输出契约（Claude Code 2.1.278）

代 allow 一次（仅此行为，不写 always／session／`updatedPermissions`／`applyRules`）：

```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
```

交回人审：exit 0 + 空 stdout。

## 已知限制

- **硬禁第二开关未做**（开工卡可选；开启前须风险 ack）。本阶段 README 标明未做。
- 默认关；无 session／always 缓存；每次独立问 Jev。
- Live 依赖 TypeSafe 额度与 `TYPESAFE_API_KEY`；脱敏是尽力而为，不是安全边界。
- 主路径只做 `PermissionRequest`；未做 PreToolUse 硬拦产品化。
- Managed／企业 deny 应由宿主优先；本闸不绕过。
- 本阶段不上架、不计费、不代持买家 Key。

## 许可

本阶段私有本地仓；是否 MIT／公开另报老板。
