#!/usr/bin/env python3
"""启动本机 Anthropic Messages 兼容代理。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from claude_jev_gate.proxy.server import serve_forever  # noqa: E402


def main() -> int:
    serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
