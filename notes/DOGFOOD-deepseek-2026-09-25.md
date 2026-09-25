# Dogfood · Claude Code × Jev gate via DeepSeek API

- Time: 2026-09-25 Asia/Shanghai
- Auth: `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` + Hermes `DEEPSEEK_API_KEY` as `ANTHROPIC_API_KEY`
- Model: `deepseek-chat` (runtime `deepseek-v4-flash`)
- Hooks: `~/.claude/settings.json` → `python3 /workspace/saas-scout/claude-jev-gate/bin/permission_request.py`
- Gate: `CLAUDE_JEV_GATE_ENABLED=true`

## Results

1. Write + MOCK=approve → PermissionRequest hook fired → allow once → file written. PASS
2. Write + MOCK=deny + `--permission-prompts none` → passthrough empty → auto-deny → file absent. PASS
3. Bash alone often auto-allowed without PermissionRequest in print mode (not a gate failure).

## Note

Do not use `--plugin-dir` together with the same PermissionRequest in user settings or the hook runs twice.
