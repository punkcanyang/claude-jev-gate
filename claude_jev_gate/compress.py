"""本地可证明启发式压缩（stub）：trim 之后才可调用。标清非上游 LLM 压缩。"""
from __future__ import annotations

from typing import Any

from .trim import estimate_chars


def heuristic_compress(
    messages: list[dict[str, Any]],
    *,
    focus_topic: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """把中间非系统消息收成一条摘要 stub。可复现；$0 证明用。"""
    msgs = [m for m in messages if isinstance(m, dict)]
    before_chars = estimate_chars(msgs)
    system = [m for m in msgs if str(m.get("role") or "") == "system"]
    rest = [m for m in msgs if str(m.get("role") or "") != "system"]
    if len(rest) <= 4:
        stats = {
            "chars_before": before_chars,
            "chars_after": before_chars,
            "messages_before": len(msgs),
            "messages_after": len(msgs),
            "stub": True,
            "skipped_short": True,
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
        "focus_topic": focus_topic,
    }
    return out, stats
