"""上下文裁剪：丢旧工具噪声、保留系统约束与最近 N 轮。"""
from __future__ import annotations

from typing import Any


def _role(m: dict[str, Any]) -> str:
    return str(m.get("role") or "")


def _is_toolish(m: dict[str, Any]) -> bool:
    role = _role(m)
    if role in ("tool", "function"):
        return True
    if role == "assistant" and m.get("tool_calls"):
        return True
    # Anthropic Messages：assistant content blocks 含 tool_use
    content = m.get("content")
    if role == "assistant" and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                return True
    if role == "user" and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return True
    return False


def estimate_chars(messages: list[dict[str, Any]]) -> int:
    n = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
        elif isinstance(c, list):
            n += sum(len(str(p)) for p in c)
        if m.get("tool_calls"):
            n += len(str(m.get("tool_calls")))
    return n


def trim_messages(
    messages: list[dict[str, Any]],
    *,
    keep_last_n_turns: int = 6,
    drop_old_tool_noise: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """返回 (trimmed, stats)。禁止在 compress 前跳过本步（由 pipeline 强制调用）。

    计轮口径（P2-6 文档化）：每条 ``role=user`` 消息开启一轮（含仅含 tool_result
    的 user 块）。这与 Anthropic「一对 user+assistant」语义不同，但对 agentic
    会话更保守（保留更多最近 user／tool_result）。若需改成「一对一轮」可后续加开关。
    """
    msgs = [m for m in messages if isinstance(m, dict)]
    before = estimate_chars(msgs)
    system = [m for m in msgs if _role(m) == "system"]
    rest = [m for m in msgs if _role(m) != "system"]

    turns: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for m in rest:
        if _role(m) == "user" and cur:
            turns.append(cur)
            cur = [m]
        else:
            cur.append(m)
    if cur:
        turns.append(cur)

    n_keep = max(1, int(keep_last_n_turns))
    kept_turns = turns[-n_keep:] if turns else []
    dropped_turns = turns[:-n_keep] if len(turns) > n_keep else []

    kept: list[dict[str, Any]] = []
    dropped_tool = 0
    for turn in dropped_turns:
        for m in turn:
            if drop_old_tool_noise and _is_toolish(m):
                dropped_tool += 1
                continue
            content = m.get("content")
            if drop_old_tool_noise and _role(m) == "assistant" and isinstance(content, str) and len(content) > 400:
                kept.append({**m, "content": content[:200] + "\n…[trimmed]"})
            else:
                kept.append(m)

    for turn in kept_turns:
        kept.extend(turn)

    out = system + kept
    after = estimate_chars(out)
    stats = {
        "chars_before": before,
        "chars_after": after,
        "messages_before": len(msgs),
        "messages_after": len(out),
        "turns_before": len(turns),
        "turns_kept": len(kept_turns),
        "tool_msgs_dropped": dropped_tool,
        "keep_last_n_turns": keep_last_n_turns,
        "drop_old_tool_noise": drop_old_tool_noise,
    }
    return out, stats
