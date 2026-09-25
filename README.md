# claude-jev-gate

<p align="center">
  <img src="./docs/readme-assets/hero.svg" width="100%" alt="claude-jev-gate: Claude Code PermissionRequest tool gate and local Anthropic-compatible proxy with three off-by-default switches">
</p>

给 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 加两件可选能力：

1. **工具闸**（`PermissionRequest` hook）：高置信 TypeSafe **Jev** `approve` → 代点**允许这一次**；`deny`／`unsure`／低置信／超时／异常 → 交回人审。不做 session／always。
2. **本机 Anthropic 兼容代理**：可选 **模型路由**（Jev Choice → 改写 model；失败 fail-open 主模型）+ **先裁再压**（强制 trim → compress）。

三开关默认**全关**，彼此独立。TypeSafe **直连**（`TYPESAFE_API_KEY`）；**禁止** Vercel AI Gateway。密钥不进仓、不打印。

<p align="center">
  <img src="./docs/readme-assets/architecture.svg" width="100%" alt="Claude Code tool gate path and local proxy path: Jev route, trim then compress, upstream DeepSeek">
</p>

## 最短上手

### 1. 先验（无需 Key）

```bash
cd /path/to/claude-jev-gate
python3 scripts/prove_gate.py            # 工具闸 13/13
python3 scripts/prove_routing.py         # ≥20 样本选型分布＋兜底
python3 scripts/prove_trim_compress.py   # 先 trim 再 compress（order_ok）
./scripts/demo_proxy_curl.sh             # 自启 mock 代理 + curl Messages
```

三 prove 必须 exit 0。报告落在 `notes/reports/`（可 gitignore）。

### 2. 起代理（可选）

```bash
cd /path/to/claude-jev-gate
export CLAUDE_JEV_UPSTREAM_MOCK=1   # 无上游 Key 时
# 可选打开路由／裁压：
# export CLAUDE_JEV_ROUTE_ENABLED=true
# export CLAUDE_JEV_TRIM_COMPRESS_ENABLED=true
# export CLAUDE_JEV_ROUTE_MOCK=heuristic

# 优先用 typesafe-venv；也可用环境变量覆盖（见下）
export CLAUDE_JEV_GATE_PYTHON="${CLAUDE_JEV_GATE_PYTHON:-python3}"
"$CLAUDE_JEV_GATE_PYTHON" bin/proxy_server.py
# 默认 http://127.0.0.1:8787
```

Claude Code 指到代理：

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
# 真打上游时：CLAUDE_JEV_UPSTREAM_MOCK=0
# + CLAUDE_JEV_UPSTREAM_BASE_URL（例：https://api.deepseek.com/anthropic）
# + CLAUDE_JEV_UPSTREAM_API_KEY（或 ANTHROPIC_API_KEY / DEEPSEEK_API_KEY）
```

### 3. 装工具闸 plugin

把本仓加为本地 Claude Code plugin（或 symlink），确保 `hooks/hooks.json` 被加载。需要时再开闸：

```bash
export CLAUDE_JEV_GATE_ENABLED=true
# Live Jev：export TYPESAFE_API_KEY=...   # 勿写入 git
# 离线演练：export CLAUDE_JEV_GATE_MOCK=approve
```

可选：把 `hooks/hooks.json` 里的 command 拷到项目 `.claude/settings.json`，把 `${CLAUDE_PLUGIN_ROOT}` 换成绝对路径。

## 三开关

| 变量 | 默认 | 含义 |
|------|------|------|
| `CLAUDE_JEV_GATE_ENABLED` | 关 | PermissionRequest 工具闸 |
| `CLAUDE_JEV_ROUTE_ENABLED` | 关 | 代理内模型路由 |
| `CLAUDE_JEV_TRIM_COMPRESS_ENABLED` | 关 | 代理内先裁再压 |

全关：可不启代理（直连上游＋原版人审）；若启代理且路由／裁压都关，则**透明转发**（不改 model、不改 messages）。

其它常用变量见 `config.example.env`（主模型／候选、上游 URL／Key、mock、trim 保留轮数、代理端口等）。

## 解释器与 TypeSafe 路径

hooks 示例与部分脚本默认指向本机 box 路径（仅作示例，可改）：

```text
# 示例（本机 box）
/workspace/tools/typesafe-venv/bin/python
```

可移植覆盖（推荐）：

| 变量 | 作用 |
|------|------|
| `CLAUDE_JEV_GATE_PYTHON` | hooks／代理用的 Python 解释器 |
| `CLAUDE_JEV_GATE_TYPESAFE_VENV` | typesafe-venv 根目录 |
| `CLAUDE_JEV_GATE_TYPESAFE_SITE_PACKAGES` | 直接指定 site-packages（可用 `:` 分隔） |

`ensure_typesafe_path` 对 site-packages **insert(0)**，避免系统旧 `typing_extensions` 抢先。需要 Python 3.10+。Live Jev 需可导入 `typesafe_sdk`。

改 hooks 里的绝对路径时，请与 `CLAUDE_JEV_GATE_PYTHON` 保持一致。

## 输出契约（工具闸，Claude Code 2.1.278）

代 allow 一次：

```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
```

交回人审：exit 0 + 空 stdout。不写 always／session／`updatedPermissions`／`applyRules`。

## 已知限制

- compress 为**本地启发式 stub**（可证明顺序），不是上游 LLM 压缩；顺序强制 trim → compress。
- 工具闸不做硬禁第二开关；默认关；无 session／always 缓存。
- Live 依赖 TypeSafe 额度与 `TYPESAFE_API_KEY`；脱敏尽力而为，非安全边界。
- 路由 fail-open 到主模型；不引入 Gateway。
- 不计费、不代持买家 Key；本仓未针对 macOS 装机／上架做专门流程。

## 目录

```text
.claude-plugin/plugin.json
hooks/hooks.json
bin/permission_request.py
bin/proxy_server.py
claude_jev_gate/
  config.py decide.py routing.py trim.py compress.py pipeline.py
  proxy/   # Anthropic Messages 兼容小服务
data/routing_samples.jsonl
scripts/prove_gate.py
scripts/prove_routing.py
scripts/prove_trim_compress.py
scripts/demo_proxy_curl.sh
config.example.env
docs/readme-assets/
```

## License

MIT — 见 [`LICENSE`](./LICENSE)。
