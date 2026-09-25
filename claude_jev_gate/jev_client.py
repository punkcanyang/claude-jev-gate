"""Jev 客户端：mock 矩阵 + live TypeSafe Choice；超时由调用方用 daemon+queue 包。"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Mapping

from .config import GateConfig, ensure_typesafe_path

_VALID = frozenset({"approve", "deny", "unsure"})


def mock_response(kind: str, timeout: float) -> dict[str, Any]:
    kind = (kind or "").strip().lower()
    if kind == "timeout":
        # 迟到的 approve 必须被丢弃：睡得比本次预算更久
        time.sleep(max(float(timeout), 0.0) + 1.0)
        return {"decision": "approve", "confidence": 0.99, "reason_code": "mock_late"}
    if kind == "error":
        raise RuntimeError("mock_jev_error")
    table = {
        "approve": {"decision": "approve", "confidence": 0.95, "reason_code": "mock_approve"},
        "deny": {"decision": "deny", "confidence": 0.95, "reason_code": "mock_deny"},
        "unsure": {"decision": "unsure", "confidence": 0.50, "reason_code": "mock_unsure"},
        "low_confidence": {"decision": "approve", "confidence": 0.40, "reason_code": "mock_low"},
        "malformed": {"decision": "APPROVE_YES", "confidence": "high", "reason_code": "x" * 200},
    }
    if kind in table:
        return dict(table[kind])
    return {"decision": "unsure", "confidence": 0.0, "reason_code": "mock_default_unsure"}


def _ask_jev_live(payload: dict[str, Any], cfg: GateConfig) -> dict[str, Any]:
    ensure_typesafe_path()
    from typesafe_sdk import Choice, TypeSafeClient

    state = (
        f"tool_name: {payload.get('tool_name')}\n"
        f"tool_input_summary: {payload.get('tool_input_summary')}\n"
        f"digest: {payload.get('digest')}\n"
        "Decide whether Claude Code should auto-allow THIS ONE PermissionRequest.\n"
        "Prefer deny/unsure when uncertain. Never approve destructive actions lightly."
    )
    questions = {
        "verdict": Choice(
            instructions=(
                "You are a safety co-pilot for Claude Code tool permissions. "
                "Return approve only when the redacted tool call is clearly safe to run once. "
                "Return deny when it looks harmful. Return unsure when ambiguous."
            ),
            criteria={
                "approve": "Safe to auto-allow once at high confidence",
                "deny": "Should not auto-allow; looks risky or disallowed",
                "unsure": "Not enough signal; hand to human",
            },
        )
    }
    model = cfg.jev_model
    with TypeSafeClient(model=model) as client:
        result = client.system_one(state=state, questions=questions, model=model)
    ans = result.choices.get("verdict")
    decision = (ans.choice if ans else None) or "unsure"
    if decision not in _VALID:
        decision = "unsure"
    confidence = float(ans.confidence) if ans and ans.confidence is not None else 0.0
    return {"decision": decision, "confidence": confidence, "reason_code": f"jev_{decision}"}


def normalize_jev_result(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    decision = str(raw.get("decision") or "").strip().lower()
    if decision not in _VALID:
        return None
    conf_raw = raw.get("confidence")
    if isinstance(conf_raw, bool) or not isinstance(conf_raw, (int, float, str)):
        return None
    try:
        confidence = float(conf_raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        return None
    reason = str(raw.get("reason_code") or f"jev_{decision}")[:64]
    return {"decision": decision, "confidence": confidence, "reason_code": reason}


def ask_jev(payload: dict[str, Any], cfg: GateConfig) -> dict[str, Any]:
    """同步询问（调用方负责 timeout 包装）。缺 Key 时直接 unsure。"""
    if cfg.mock:
        return mock_response(cfg.mock, cfg.timeout_seconds)
    if not os.environ.get("TYPESAFE_API_KEY"):
        return {"decision": "unsure", "confidence": 0.0, "reason_code": "missing_typesafe_key"}
    return _ask_jev_live(payload, cfg)
