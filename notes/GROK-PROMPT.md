# 任务：在本仓落地 Claude Code × Jev 工具闸（一次干完）

工作目录就是本仓：`/workspace/saas-scout/claude-jev-gate`（已有 `notes/TASK.md`）。
规格：读 `/workspace/bd-punkcan/开工卡-Claude-Code-Jev工具闸-2026-09-25.md` 与 `notes/TASK.md`。
**禁止** fork `/workspace/saas-scout/hermes-jev-router`；可**借鉴行为**（脱敏、mock 矩阵、daemon+queue 超时、TypeSafe 路径注入）。

## 硬约束
1. Claude Code 事件名必须是 **PermissionRequest**（不是 PreToolUse 作主路径）。
2. 代 allow 一次时，stdout **仅**输出这一行 JSON（无多余字段）：
```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
```
禁止 `updatedPermissions`／`applyRules`／`always`／session 缓存。
3. 交回人审：exit 0 + **空 stdout**（不输出 decision）。
4. 默认关：`CLAUDE_JEV_GATE_ENABLED` 缺省／false／0／off／no → 关 → 交回人审。
5. 置信门槛默认 `0.80`（env `CLAUDE_JEV_GATE_MIN_CONFIDENCE` 可改，但 floor ≥ 0.5）。
6. 禁 Gateway。Live 用 `TYPESAFE_API_KEY` + typesafe_sdk。SDK 路径借鉴 hermes `routing.py` 的 `_ensure_typesafe_path`／`_typesafe_site_dirs`，env：
   - `CLAUDE_JEV_GATE_TYPESAFE_SITE_PACKAGES`（os.pathsep 多分隔）
   - `CLAUDE_JEV_GATE_TYPESAFE_VENV`
   本机已知：`/workspace/tools/typesafe-venv`
7. 超时：daemon 线程 + `queue.Queue`（**勿** `with ThreadPoolExecutor`）。默认约 8s，env `CLAUDE_JEV_GATE_TIMEOUT_SECONDS`。
8. Mock：env `CLAUDE_JEV_GATE_MOCK=approve|deny|unsure|low_confidence|timeout|error|malformed`
9. 第二开关硬禁：本阶段**不做**；README／HANDOFF 写「未做」。
10. `git init` 本地私有即可；**不要 push／公开**。
11. 完成后 `python3 scripts/prove_gate.py` 必须 exit 0。把本 session id 写入 `notes/TASK.md`。

## 必须创建的布局
```
.claude-plugin/plugin.json
hooks/hooks.json
bin/permission_request.py          # shebang python3；读 stdin JSON → 判 → stdout
claude_jev_gate/
  __init__.py
  config.py                        # enabled / min_confidence / timeout / mock / typesafe path envs
  redact.py                        # 脱敏 tool 名／参数摘要；digest（sha256 截断）
  timeouts.py                      # call_with_timeout：daemon + queue
  jev_client.py                    # mock + live TypeSafe Choice approve|deny|unsure
  decide.py                        # 核心：enabled? → ask → allow_once | passthrough
  events.py                        # ~/.claude/claude-jev-gate/events.jsonl（可用 CLAUDE_JEV_GATE_EVENTS_PATH 覆盖）；只记 digest/decision/confidence/latency/reason；无密钥／完整命令
scripts/prove_gate.py              # mock 矩阵，失败 exit≠0
README.md
notes/HANDOFF-bd.md
config.example.env
.gitignore                         # 含 .env、__pycache__、events、.grok 等
```

## hooks/hooks.json
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

## .claude-plugin/plugin.json
合理最小：name `claude-jev-gate`，version `0.1.0`，description 简述 Jev 工具闸／自动同意一次，hooks 指向 `./hooks/hooks.json`（按 Claude Code plugin 惯例）。

## decide 口径
- disabled → passthrough（空 stdout，exit 0）
- enabled + mock/live 得 `approve` 且 confidence ≥ min → stdout allow JSON，exit 0
- deny／unsure／low_confidence／malformed／timeout／error／缺 Key（live）→ passthrough（空 stdout，exit 0）
- 脚本自身崩溃应尽量 catch 后 passthrough；prove 里「失败非0」指 **prove_gate.py 断言失败**，不是 hook 对业务失败非0

## stdin 示例（PermissionRequest）
```json
{"hook_event_name":"PermissionRequest","tool_name":"Bash","tool_input":{"command":"ls -la"},"session_id":"s1"}
```
兼容常见字段：`tool_name`／`tool_input`；也可容忍 `toolName`／`toolInput`。

## Jev schema（mock 与 live 归一）
```json
{"decision":"approve|deny|unsure","confidence":0.0,"reason_code":"short_nonsecret"}
```
malformed mock：非法 decision／非数值 confidence → 归一失败 → passthrough。
timeout mock：睡 `timeout+1` 再返回迟到 approve → 必须被超时丢弃 → passthrough。
error mock：抛异常 → passthrough。

## scripts/prove_gate.py 验收矩阵（全绿才 exit 0）
在临时目录跑，清掉相关 env，用 subprocess 调 `bin/permission_request.py`（或直接 import decide）均可，但必须覆盖：
1. disabled（缺省）→ 空 stdout
2. enabled + MOCK=approve → stdout 含 hookEventName PermissionRequest 且 behavior allow；无 updatedPermissions／always
3. MOCK=deny → 空 stdout
4. MOCK=unsure → 空
5. MOCK=low_confidence → 空
6. MOCK=timeout → 空，且墙钟大致在 timeout 量级返回（别挂死）
7. MOCK=error → 空
8. MOCK=malformed → 空
9. enabled 但无 MOCK 且无 TYPESAFE_API_KEY → 空（fail-closed）
10. 日志／events 若写出：不含密钥样例串、不含完整敏感命令（可选强断言）
任一失败 print 原因并 `sys.exit(1)`；全绿 print 摘要 `sys.exit(0)`。

## README.md（中文可）
安装（plugin 路径／CLAUDE_PLUGIN_ROOT 或 settings hooks）、开关（CLAUDE_JEV_GATE_ENABLED）、怎么验（prove_gate.py）、已知限制（硬禁第二开关未做；默认关；无 session 缓存；live 需 TypeSafe Key；本阶段以 PermissionRequest 为主）。

## notes/HANDOFF-bd.md
给商务拓展：仓路径、怎么装、怎么开、怎么测、prove 结果、已知限制、session id。

## 验收命令
```bash
cd /workspace/saas-scout/claude-jev-gate && python3 scripts/prove_gate.py
```
必须 exit 0。可选 printf 模拟 stdin 抽查 bin。

干完后：更新 `notes/TASK.md` 写上本 session id／标题／状态 READY；不要半成品停。
