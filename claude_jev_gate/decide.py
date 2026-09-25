"""核心判决：enabled？→ ask Jev → allow once 或交回人审。"""
from __future__ import annotations

import time
from typing import Any

from .config import GateConfig, load_config
from .events import emit
from .jev_client import ask_jev, normalize_jev_result
from .redact import summarize_tool
from .timeouts import FuturesTimeout, call_with_timeout

ALLOW_STDOUT = (
    '{"hookSpecificOutput":{"hookEventName":"PermissionRequest",'
    '"decision":{"behavior":"allow"}}}'
)

OUTCOME_ALLOW = "allow_once"
OUTCOME_PASSTHROUGH = "passthrough"

JEV_INPUT_LIMIT = 4000


def _extract_tool(event: dict[str, Any]) -> tuple[str, Any]:
    name = event.get("tool_name") or event.get("toolName") or ""
    inp = event.get("tool_input")
    if inp is None:
        inp = event.get("toolInput")
    if inp is None:
        inp = {}
    return str(name), inp


def decide(event: dict[str, Any] | None, cfg: GateConfig | None = None) -> dict[str, Any]:
    """返回 {outcome, stdout, reason, ...}。outcome=allow_once|passthrough。"""
    cfg = cfg or load_config()
    t0 = time.monotonic()

    if not cfg.enabled:
        return {
            "outcome": OUTCOME_PASSTHROUGH,
            "stdout": "",
            "reason": "disabled",
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    event = event if isinstance(event, dict) else {}
    tool_name, tool_input = _extract_tool(event)
    summary = summarize_tool(tool_name, tool_input, limit=JEV_INPUT_LIMIT)
    payload = {
        "tool_name": summary["tool_name"],
        "tool_input_summary": summary["tool_input_summary"],
        "digest": summary["digest"],
    }

    decided_by = "mock" if cfg.mock else "jev"
    raw: Any = None
    error_class: str | None = None
    if summary["truncated"]:
        # Jev 只看得到前缀，放行的却是完整调用：不问，直接交回人审
        error_class = "input_too_long"
        decided_by = "gate"
    else:
        try:
            raw = call_with_timeout(lambda: ask_jev(payload, cfg), cfg.timeout_seconds)
        except FuturesTimeout:
            error_class = "timeout"
        except Exception:  # noqa: BLE001
            error_class = "error"

    latency_ms = int((time.monotonic() - t0) * 1000)
    normalized = None if error_class else normalize_jev_result(raw)

    if error_class:
        reason = error_class
        outcome = OUTCOME_PASSTHROUGH
        stdout = ""
        conf = None
        decision = None
    elif normalized is None:
        reason = "malformed"
        outcome = OUTCOME_PASSTHROUGH
        stdout = ""
        conf = None
        decision = None
    elif (
        normalized["decision"] == "approve"
        and float(normalized["confidence"]) >= cfg.min_confidence
    ):
        reason = normalized["reason_code"]
        outcome = OUTCOME_ALLOW
        stdout = ALLOW_STDOUT
        conf = normalized["confidence"]
        decision = normalized["decision"]
    else:
        reason = normalized["reason_code"]
        if normalized["decision"] == "approve":
            reason = "low_confidence"
        outcome = OUTCOME_PASSTHROUGH
        stdout = ""
        conf = normalized["confidence"]
        decision = normalized["decision"]

    try:
        emit(
            cfg.events_path,
            "permission_request",
            digest=summary["digest"],
            tool_name=summary["tool_name"],
            outcome=outcome,
            decision=decision,
            confidence=conf,
            latency_ms=latency_ms,
            reason=reason,
            decided_by=decided_by,
            error_class=error_class,
        )
    except Exception:  # noqa: BLE001
        pass

    return {
        "outcome": outcome,
        "stdout": stdout,
        "reason": reason,
        "decision": decision,
        "confidence": conf,
        "latency_ms": latency_ms,
        "digest": summary["digest"],
    }
