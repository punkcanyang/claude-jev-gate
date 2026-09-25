#!/usr/bin/env python3
"""Claude Code PermissionRequest hook entry：stdin JSON → allow once 或交回人审。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from claude_jev_gate.decide import decide  # noqa: E402


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        return 0
    event: dict = {}
    if raw and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                event = parsed
        except Exception:  # noqa: BLE001
            event = {}
    try:
        result = decide(event)
        out = result.get("stdout") or ""
        if out:
            sys.stdout.write(out if out.endswith("\n") else out + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001
        # fail-closed：任何内部异常都交回人审
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
