# 任务：扩现仓落地 Anthropic 兼容代理 + 模型路由 + 先裁再压（一次干完）

工作目录：`/workspace/saas-scout/claude-jev-gate`（已有工具闸 READY；**扩现仓，不另开、不 fork hermes**）。
读：`notes/TASK.md` 与 `/workspace/bd-punkcan/开工卡-Claude-Code-路由与裁压-2026-09-25.md`。
对照（只读借鉴行为／顺序／样本矩阵，**禁止拷贝仓／宿主补丁**）：
- `/workspace/saas-scout/hermes-jev-router/routing.py`
- `/workspace/saas-scout/hermes-jev-router/trim.py`
- `/workspace/saas-scout/hermes-jev-router/engine.py`（trim→compress 顺序）
- `/workspace/saas-scout/hermes-jev-router/scripts/prove_trim_compress.py`
- `/workspace/saas-scout/hermes-jev-router/scripts/eval_routing.py`
- `/workspace/saas-scout/hermes-jev-router/data/routing_samples.jsonl`（可改编为本仓 data）

本 session id 必须保留：`fb705f48-aa5d-4162-8fb1-6f27d5a6e78e`。禁止 Fast；high reasoning。$0；禁 Vercel AI Gateway；TypeSafe 直连；不动老板 Mac；不上架。

## 硬约束
1. **保留** PermissionRequest 工具闸与 `CLAUDE_JEV_GATE_ENABLED`；`scripts/prove_gate.py` 必须仍 13/13 绿。
2. 三开关分开，默认全关：
   - `CLAUDE_JEV_GATE_ENABLED`（闸）
   - `CLAUDE_JEV_ROUTE_ENABLED`（路由）
   - `CLAUDE_JEV_TRIM_COMPRESS_ENABLED`（裁压）
3. 全关时：代理应**透明转发**（不改 model、不裁压）；或可不启代理。行为可预期。
4. 路由 fail-open：低置信／超时／异常 → **默认主模型**，不堵对话。
5. 进入压缩前必须 **trim → compress**；pipeline 强制顺序；事件或长度证明；禁止不裁直接压。
6. 密钥只环境变量。上游可为 DeepSeek Anthropic 兼容口或 mock。
7. hooks 命令**不要裸 python3**：用 `/workspace/tools/typesafe-venv/bin/python` 或 `${CLAUDE_JEV_GATE_PYTHON}`（README 默认指向 typesafe-venv）。
8. `ensure_typesafe_path`：对 site-packages **insert(0)**（本仓），避免系统旧 typing_extensions 抢先。
9. 完成后三 prove 全绿：prove_gate + prove_routing + prove_trim_compress。本地 commit 勿 push。
10. 更新 README／config.example.env／notes/HANDOFF-bd.md／notes/TASK.md（session id 不变）。

## 必须创建／改的布局
```
claude_jev_gate/
  config.py              # 扩：route/trim 开关、模型候选、主模型、阈值、trim 参数；ensure_typesafe_path insert(0)
  routing.py             # Jev／mock／启发式选型；fail-open 主模型
  trim.py                # 本地 trim（保留系统＋最近 N 轮；丢旧工具噪声）
  compress.py            # 可证明本地 stub／启发式压缩（标清是 stub）
  pipeline.py            # apply_trim_then_compress：强制顺序；写 events
  proxy/
    __init__.py
    server.py            # HTTP：POST /v1/messages（+ optional /v1/messages/count_tokens 可省略）
    forward.py           # 转发上游；支持 CLAUDE_JEV_UPSTREAM_BASE_URL + key；mock 模式
  ...现有 decide/jev_client/events/timeouts/redact 保留
bin/proxy_server.py      # 入口：python -m 或直接跑
bin/permission_request.py # 保留；hooks 解释器改 typesafe-venv
hooks/hooks.json         # command 用 typesafe-venv python 或 ${CLAUDE_JEV_GATE_PYTHON:-/workspace/tools/typesafe-venv/bin/python}
data/routing_samples.jsonl  # ≥20 条 simple/complex/tool_heavy/long_context
scripts/prove_gate.py       # 保留
scripts/prove_routing.py    # ≥20 样本；选型分布；兜底；关路由→全主模型；失败 exit≠0
scripts/prove_trim_compress.py  # 超长上下文；断言 trim 在 compress 前（事件顺序或 pipeline）
scripts/demo_proxy_curl.sh  # 可选：演示经代理打 messages（mock 上游）
README.md
config.example.env
notes/HANDOFF-bd.md
notes/TASK.md
```

## 代理行为
- 监听 `CLAUDE_JEV_PROXY_HOST`/`CLAUDE_JEV_PROXY_PORT`（默认 127.0.0.1:8787）
- `POST /v1/messages`：解析 Anthropic 形 body（model, messages, system, max_tokens, …）
- 若 `CLAUDE_JEV_TRIM_COMPRESS_ENABLED`：对 messages（含 system）走 pipeline trim→compress，再放入转发 body
- 若 `CLAUDE_JEV_ROUTE_ENABLED`：用 routing.route_turn 选 model，写入转发 body 的 model（或映射到上游模型名）
- 转发到 `CLAUDE_JEV_UPSTREAM_BASE_URL`（例 DeepSeek Anthropic 兼容 `https://api.deepseek.com/anthropic`）+ `CLAUDE_JEV_UPSTREAM_API_KEY` 或 `ANTHROPIC_API_KEY`／`DEEPSEEK_API_KEY`
- `CLAUDE_JEV_UPSTREAM_MOCK=1`：不真打上游，返回固定 Anthropic messages 形假响应（供 curl／prove）
- 健康检查 `GET /healthz` → 200

## 路由标签（与 hermes 思路对齐，本仓独立实现）
cheap / primary / complex / tool_heavy / long_context
环境变量示例：
- `CLAUDE_JEV_PRIMARY_MODEL=deepseek-chat`（或 deepseek-reasoner／claude…）
- `CLAUDE_JEV_MODEL_CHEAP=...`
- `CLAUDE_JEV_MODEL_COMPLEX=...`
- `CLAUDE_JEV_MODEL_TOOL_HEAVY=...`
- `CLAUDE_JEV_MODEL_LONG_CONTEXT=...`
- `CLAUDE_JEV_ROUTE_MIN_CONFIDENCE=0.55`
- `CLAUDE_JEV_ROUTE_MOCK=heuristic|label:cheap|timeout|error|low_confidence`（离线证明）

无 Key／dry／mock heuristic：可用规则粗分但仍 fail-open 低置信到主模型。

## 裁压
- trim：保留 system；按 user 起轮保留最近 N（`CLAUDE_JEV_TRIM_KEEP_LAST_N=6`）；旧轮丢 tool／function／tool_calls 噪声
- compress：本地 stub——中间消息收成一条 `[claude-jev-gate compressed summary]`；**必须**在 trim 之后调用
- pipeline 写 events：type=trim 然后 type=compress；`last_pipeline` 可查
- 关 `CLAUDE_JEV_TRIM_COMPRESS_ENABLED`：代理不改 messages

## prove_routing 期望
- 读 data/routing_samples.jsonl ≥20
- 开路由 + mock/heuristic：有选型分布（不全是同一 label 也可，但要有分布或至少覆盖多 bucket 的 expect）
- 断言：低置信／timeout／error mock → model==primary 且 fallback
- 关路由 → 全部 primary
- 失败 assert → exit≠0；成功打印 GREEN

## prove_trim_compress 期望
- 构造 ≥40 轮超长（含 tool 噪声）
- 开裁压跑 pipeline；断言 events 或 pipeline 中 trim 索引 < compress 索引
- 输出变短（chars_after < chars_before 或 messages_out < messages_in）
- 失败 exit≠0

## hooks.json 改法
```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_JEV_GATE_PYTHON:-/workspace/tools/typesafe-venv/bin/python} ${CLAUDE_PLUGIN_ROOT}/bin/permission_request.py"
          }
        ]
      }
    ]
  }
}
```
（若 Claude Code 不展开默认值语法，README 写死绝对路径 `/workspace/tools/typesafe-venv/bin/python`。）

## README 必须写
怎么设 `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`、三开关、起代理命令、三 prove、mock 上游、已知限制（stub compress、默认关、不上架、禁 Gateway）。

## 验收命令（做完必须全绿）
```bash
cd /workspace/saas-scout/claude-jev-gate
python3 scripts/prove_gate.py
python3 scripts/prove_routing.py
python3 scripts/prove_trim_compress.py
# 可选：起代理 + curl demo
```

立刻落文件实现；不要只写方案。做完更新 HANDOFF／TASK 状态 READY，本地 git commit。
