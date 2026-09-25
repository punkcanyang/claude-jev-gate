"""脱敏与摘要：尽力而为，不是安全边界。"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_QUOTED_OR_WORD = r"(\"[^\"]*\"|'[^']*'|\S+)"

_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]+"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_.\-]*(?:api[_-]?key|token|passw(?:or)?d|secret|access[_-]?key"
            r"|private[_-]?key|credential|auth)[A-Za-z0-9_.\-]*)(\s*[=:]\s*)" + _QUOTED_OR_WORD
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"(?i)(--?(?:password|passwd|token|api[_-]?key|secret)\s+)" + _QUOTED_OR_WORD),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
            r"|xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}|SECRET\d+)\b"
        ),
        "[REDACTED]",
    ),
]


def scrub(text: Any, limit: int = 400) -> str:
    s = str(text or "")
    for pattern, repl in _REDACT_PATTERNS:
        s = pattern.sub(repl, s)
    return s[:limit]


def digest_of(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()[:32]


def summarize_tool(tool_name: str, tool_input: Any, *, limit: int = 400) -> dict[str, str]:
    name = scrub(tool_name, limit=80)
    if isinstance(tool_input, (dict, list)):
        try:
            raw = json.dumps(tool_input, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            raw = str(tool_input)
    else:
        raw = str(tool_input or "")
    summary = scrub(raw, limit=limit)
    return {
        "tool_name": name,
        "tool_input_summary": summary,
        "digest": digest_of(name, summary),
    }
