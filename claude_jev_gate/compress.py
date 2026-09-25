"""本地可证明启发式压缩（stub）：trim 之后才可调用。标清非上游 LLM 压缩。"""
from __future__ import annotations

from typing import Any

from .trim import estimate_chars

# P2-6 默认门槛：避免「刚过 4 条就猛砍」
DEFAULT_MIN_MESSAGES = 8
DEFAULT_MIN_CHARS = 8000


def heuristic_compress(
    messages: list[dict[str, Any]],
    *,
    focus_topic: str | None = None,
    min_messages: int = DEFAULT_MIN_MESSAGES,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把中间非系统消息收成一条摘要 stub。可复现；$0 证明用。

    仅当非 system 消息数 ≥ min_messages **且** 总 chars ≥ min_chars 才压缩；
    否则原样返回（skipped_short / skipped_below_threshold）。
    """
    msgs = [m for m in messages if isinstance(m, dict)]
    before_chars = estimate_chars(msgs)
    system = [m for m in msgs if str(m.get("role") or "") == "system"]
    rest = [m for m in msgs if str(m.get("role") or "") != "system"]
    min_messages = max(1, int(min_messages))
    min_chars = max(0, int(min_chars))

    if len(rest) < min_messages or before_chars < min_chars:
        stats = {
            "chars_before": before_chars,
            "chars_after": before_chars,
            "messages_before": len(msgs),
            "messages_after": len(msgs),
            "stub": True,
            "skipped_short": True,
            "skipped_below_threshold": True,
            "min_messages": min_messages,
            "min_chars": min_chars,
            "focus_topic": focus_topic,
        }
        return list(msgs), stats

    head = rest[:1]
    tail = rest[-3:]
    mid = rest[1:-3]
    mid_chars = estimate_chars(mid)
    topic = f" focus={focus_topic}" if focus_topic else ""
    summary = {
        "role": "user",
        "content": (
            f"[claude-jev-gate compressed summary{topic}] "
            f"Dropped {len(mid)} mid messages (~{mid_chars} chars). "
            "Earlier tool noise removed; keep constraints from system + recent turns. "
            "(local heuristic stub — not upstream LLM compress)"
        ),
    }
    out = system + head + [summary] + tail
    after_chars = estimate_chars(out)
    stats = {
        "chars_before": before_chars,
        "chars_after": after_chars,
        "messages_before": len(msgs),
        "messages_after": len(out),
        "mid_dropped": len(mid),
        "stub": True,
        "min_messages": min_messages,
        "min_chars": min_chars,
        "focus_topic": focus_topic,
    }
    return out, stats
