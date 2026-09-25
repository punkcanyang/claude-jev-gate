# claude-jev-gate

Claude Code **plugin／hooks** + 本机 **Anthropic Messages 兼容代理**：

1. **工具闸**（`PermissionRequest`）：高置信 Jev `approve` → 代点允许这一次；其余交回人审。
2. **模型路由**：代理内用 TypeSafe Jev 直连选型；低置信／超时／异常 → **默认主模型**（fail-open）。
3. **先裁再压**：代理内强制 **trim → compress**（本地启发式 stub，可证明顺序）。

三开关默认**全关**，彼此独立。不 fork `hermes-jev-router`（只借鉴行为／顺序／样本矩阵思路）。**禁止** Vercel AI Gateway。本阶段不上架、不动老板 Mac、$0。

## 布局

```
.claude-plugin/plugin.json
hooks/hooks.json
bin/permission_request.py
bin/proxy_server.py
claude_jev_gate/
  config.py routing.py trim.py compress.py pipeline.py
  proxy/   # Anthropic 兼容小服务
data/routing_samples.jsonl
scripts/prove_gate.py
scripts/prove_routing.py
scripts/prove_trim_compress.py
scripts/demo_proxy_curl.sh
```

## 安装

1. **工具闸 plugin**：把本仓加为本地 Claude Code plugin（或 symlink），确保 `hooks/hooks.json` 被加载。  
   Hook 命令已写死 `/workspace/tools/typesafe-venv/bin/python`（勿裸 `python3`；可用 `CLAUDE_JEV_GATE_PYTHON` 覆盖时请同步改 hooks）。
2. **项目 settings hooks**（可选）：把 `hooks/hooks.json` 里的 command 拷到 `.claude/settings.json`，`${CLAUDE_PLUGIN_ROOT}` 换成绝对路径。
3. **代理**：见下「起代理」。Claude Code 设 `ANTHROPIC_BASE_URL` 指到代理。

需要 Python 3.10+。Live Jev 需 `typesafe_sdk`（本机：`/workspace/tools/typesafe-venv`）。`ensure_typesafe_path` 对 site-packages **insert(0)**，避免系统旧 `typing_extensions` 抢先。

## 三开关

| 变量 | 默认 | 含义 |
|------|------|------|
| `CLAUDE_JEV_GATE_ENABLED` | 关 | PermissionRequest 工具闸 |
| `CLAUDE_JEV_ROUTE_ENABLED` | 关 | 代理内模型路由 |
| `CLAUDE_JEV_TRIM_COMPRESS_ENABLED` | 关 | 代理内先裁再压 |

全关：可不启代理（直连上游＋原版人审）；若启代理且两开关关，则**透明转发**（不改 model、不改 messages）。

其它常用变量见 `config.example.env`（主模型／候选、上游 URL／Key、mock、trim 保留轮数等）。

## 起代理

```bash
cd /workspace/saas-scout/claude-jev-gate
export CLAUDE_JEV_UPSTREAM_MOCK=1   # 无 Key 时
# 可选打开路由／裁压：
# export CLAUDE_JEV_ROUTE_ENABLED=true
# export CLAUDE_JEV_TRIM_COMPRESS_ENABLED=true
# export CLAUDE_JEV_ROUTE_MOCK=heuristic
/workspace/tools/typesafe-venv/bin/python bin/proxy_server.py
# 默认 http://127.0.0.1:8787
```

Claude Code：

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
# 上游真打时再设 CLAUDE_JEV_UPSTREAM_BASE_URL + CLAUDE_JEV_UPSTREAM_API_KEY
# （或 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY）；并 CLAUDE_JEV_UPSTREAM_MOCK=0
```

一键演示（自启 mock 代理 + curl）：

```bash
./scripts/demo_proxy_curl.sh
```

## 怎么验

```bash
cd /workspace/saas-scout/claude-jev-gate
python3 scripts/prove_gate.py            # 工具闸 13/13
python3 scripts/prove_routing.py         # ≥20 样本选型分布＋兜底
python3 scripts/prove_trim_compress.py   # 先 trim 再 compress
./scripts/demo_proxy_curl.sh             # 经代理打 Messages 形请求
```

三 prove 必须 exit 0。报告落在 `notes/reports/`。

## 输出契约（工具闸，Claude Code 2.1.278）

代 allow 一次：

```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
```

交回人审：exit 0 + 空 stdout。不写 always／session／`updatedPermissions`／`applyRules`。

## 已知限制

- compress 为**本地启发式 stub**（标清），非上游 LLM 压缩；顺序强制 trim→compress。
- 硬禁第二开关未做（工具闸）；默认关；无 session／always 缓存。
- Live 依赖 TypeSafe 额度与 `TYPESAFE_API_KEY`；脱敏尽力而为，非安全边界。
- 路由 fail-open 到主模型；不引入 Gateway。
- 本阶段不上架、不计费、不代持买家 Key、不动老板 Mac。

## 许可

本阶段私有本地仓；是否公开另报老板。
