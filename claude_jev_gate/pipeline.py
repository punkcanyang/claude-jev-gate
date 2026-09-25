"""强制 trim → compress 顺序；禁止不裁直接压。"""
from __future__ import annotations

import copy
from typing import Any

from .compress import heuristic_compress
from .config import TrimCompressConfig, load_trim_compress_config
from .events import emit
from .trim import estimate_chars, trim_messages

_LAST_PIPELINE: list[dict[str, Any]] = []


def get_last_pipeline() -> list[dict[str, Any]]:
    return list(_LAST_PIPELINE)


def apply_trim_then_compress(
    messages: list[dict[str, Any]],
    *,
    cfg: TrimCompressConfig | None = None,
    focus_topic: str | None = None,
    force: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """始终先 trim 再 compress。cfg.enabled=False 且非 force → 原样返回。

    返回 (messages_out, pipeline_steps)。pipeline[0] 以 trim 开头，pipeline[1]==compress。
    """
    global _LAST_PIPELINE
    cfg = cfg or load_trim_compress_config()
    msgs = copy.deepcopy(messages)
    pipeline: list[dict[str, Any]] = []
    event_log = cfg.events_path

    if not cfg.enabled and not force:
        _LAST_PIPELINE = []
        return msgs, pipeline

    # --- 步骤 1：TRIM（永远在 compress 前）---
    trimmed, tstats = trim_messages(
        msgs,
        keep_last_n_turns=cfg.keep_last_n_turns,
        drop_old_tool_noise=cfg.drop_old_tool_noise,
    )
    step_trim = {"step": "trim", "order": 1, **tstats}
    pipeline.append(step_trim)
    emit(event_log, "trim", order=1, **tstats)
    msgs = trimmed

    # --- 步骤 2：COMPRESS（永远在 trim 之后）---
    compressed, cstats = heuristic_compress(msgs, focus_topic=focus_topic)
    step_compress = {"step": "compress", "order": 2, **cstats}
    pipeline.append(step_compress)
    emit(event_log, "compress", order=2, **cstats)

    order_ok = (
        len(pipeline) >= 2
        and str(pipeline[0].get("step", "")).startswith("trim")
        and pipeline[1].get("step") == "compress"
    )
    emit(
        event_log,
        "trim_then_compress_pipeline",
        pipeline=pipeline,
        order_ok=order_ok,
        chars_in=estimate_chars(messages if isinstance(messages, list) else []),
        chars_out=estimate_chars(compressed),
    )
    _LAST_PIPELINE = list(pipeline)
    return compressed, pipeline
