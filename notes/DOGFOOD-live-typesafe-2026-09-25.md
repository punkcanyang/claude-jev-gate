# Dogfood · live TypeSafe Jev

- 2026-09-25 Asia/Shanghai
- Claude Code via DeepSeek Anthropic-compat
- Hook interpreter: `/workspace/tools/typesafe-venv/bin/python` (system `python3` hits ImportError: typing_extensions.Sentinel)
- No MOCK; TYPESAFE_API_KEY set; model jev-latest; min confidence 0.80

## Direct hook (stdin)

| tool | conf | outcome |
|------|------|---------|
| Write /tmp/hello.txt hi | 0.94 | allow_once |
| Bash echo hello | 0.99 | allow_once |
| Read /tmp/hello.txt | 0.89 | allow_once |
| Write LIVE_OK longer | 0.69 | passthrough low_confidence |

## Claude Code -p e2e

- Write LIVE_E2E → Jev approve@0.70 → low_confidence passthrough → auto-deny (no prompt surface). FAIL-CLOSED OK
- Write /tmp/hello.txt `hi` → see events below this run

## Install note for BD

Prefer venv python in settings hook command until product inserts typesafe site-packages ahead of system pkgs.
