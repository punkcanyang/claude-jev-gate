# TASK · Claude Code × 路由 + 先裁再压（扩工具闸）

## Session
- 工具: Grok Builder 4.7（禁止 Fast；default_reasoning_effort=high）
- session id: `fb705f48-aa5d-4162-8fb1-6f27d5a6e78e`（**同一任务复用**）
- 标题: Claude Code × 路由＋裁压（扩闸）
- 状态: **READY**（prove_gate + prove_routing + prove_trim_compress 全绿；代理 mock demo 绿）

## 目标（已完成）
扩现仓 `/workspace/saas-scout/claude-jev-gate`：
1. 本机 Anthropic Messages 兼容代理
2. 模型路由（TypeSafe Jev 直连；fail-open 主模型）
3. 先裁再压（trim → compress）
4. 三开关分开默认关；hooks 用 typesafe-venv；ensure_typesafe_path insert(0)

## 验收勾选
- [x] README 能起代理；demo curl 经代理（mock 上游）
- [x] ≥20 样本路由分布＋兜底；`scripts/prove_routing.py` exit 0
- [x] 超长上下文证明先 trim 再 compress；`scripts/prove_trim_compress.py` exit 0
- [x] `scripts/prove_gate.py` 13/13 绿
- [x] 未引入 Gateway
- [x] HANDOFF／config.example.env／hooks typesafe-venv

## 开工卡
`/workspace/bd-punkcan/开工卡-Claude-Code-路由与裁压-2026-09-25.md`
