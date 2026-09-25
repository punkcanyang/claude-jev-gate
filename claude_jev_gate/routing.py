"""Jev（TypeSafe 直连）模型路由：Choice + confidence；失败／低置信 → 客户端 model／主模型（fail-open）。

超时后后台 daemon 线程仍可能跑完一次 Jev（见 timeouts.call_with_timeout）；不 wait、不失控。
"""
from __future__ import annotations

import os
import time
from typing import Any

from .config import RouteConfig, ensure_typesafe_path, load_route_config
from .events import emit
from .redact import scrub
from .timeouts import FuturesTimeout, call_with_timeout

_BUCKET_TO_LABEL = {
    "simple": "cheap",
    "complex": "complex",
    "tool-heavy": "tool_heavy",
    "tool_heavy": "tool_heavy",
    "long-context": "long_context",
    "long_context": "long_context",
    "primary": "primary",
}


def _heuristic_route(text: str, cfg: RouteConfig, meta: dict[str, Any]) -> dict[str, Any]:
    """无密钥／mock heuristic：规则粗分；bucket 明确时给够门槛置信。

    P2-8：只扫 user 侧文本（调用方应传入 extract_user_text(..., include_system=False)），
    避免 Claude Code 长 system 里的 tool 字样几乎总判 tool_heavy。
    """
    t = (text or "").lower()
    labels = cfg.models
    bucket = str(meta.get("bucket") or "").strip().lower()
    if bucket in _BUCKET_TO_LABEL:
        label = _BUCKET_TO_LABEL[bucket]
        model = labels.get(label) or cfg.primary_model
        return {
            "label": label,
            "model": model,
            "confidence": 0.72,
            "fallback": False,
            "reason": "heuristic_bucket",
            "backend": "heuristic",
        }

    toolish = any(
        k in t
        for k in ("tool", "shell", "终端", "命令", "文件", "patch", "browser", "grep", "跑评测", "pytest")
    )
    longish = (
        len(text or "") > 1200
        or int(meta.get("approx_tokens") or 0) > 8000
    )
    complexish = any(
        k in t for k in ("设计", "架构", "推理", "证明", "多步", "refactor", "architecture", "why", "对比")
    )
    simpleish = len(t) < 40 and not toolish and not complexish

    if toolish:
        label = "tool_heavy"
        conf = 0.70
    elif longish:
        label = "long_context"
        conf = 0.70
    elif complexish:
        label = "complex"
        conf = 0.70
    elif simpleish:
        label = "cheap"
        conf = 0.70
    else:
        label = "primary"
        conf = 0.40  # 模糊 → 可能 fail-open 主模型

    model = labels.get(label) or cfg.primary_model
    return {
        "label": label,
        "model": model,
        "confidence": conf,
        "fallback": False,
        "reason": "heuristic_rules",
        "backend": "heuristic",
    }


def _mock_route(kind: str, cfg: RouteConfig, text: str, meta: dict[str, Any]) -> dict[str, Any]:
    kind = (kind or "").strip().lower()
    labels = cfg.models
    if kind in ("", "heuristic", "auto"):
        return _heuristic_route(text, cfg, meta)
    if kind == "timeout":
        time.sleep(max(float(cfg.timeout_seconds), 0.0) + 1.0)
        return {
            "label": "cheap",
            "model": labels.get("cheap") or cfg.primary_model,
            "confidence": 0.99,
            "fallback": False,
            "reason": "mock_late",
            "backend": "mock",
        }
    if kind == "error":
        raise RuntimeError("mock_route_error")
    if kind == "low_confidence":
        return {
            "label": "cheap",
            "model": labels.get("cheap") or cfg.primary_model,
            "confidence": 0.20,
            "fallback": False,
            "reason": "mock_low",
            "backend": "mock",
        }
    if kind.startswith("label:"):
        label = kind.split(":", 1)[1].strip()
        if label not in labels:
            label = "primary"
        return {
            "label": label,
            "model": labels[label],
            "confidence": 0.90,
            "fallback": False,
            "reason": "mock_label",
            "backend": "mock",
        }
    # 未知 mock → heuristic
    return _heuristic_route(text, cfg, meta)


def _jev_choice(text: str, cfg: RouteConfig, meta: dict[str, Any]) -> dict[str, Any]:
    ensure_typesafe_path()
    from typesafe_sdk import Choice, TypeSafeClient

    labels = cfg.models
    criteria = {
        "cheap": f"简单问答／短指令；走便宜模型 {labels['cheap']}",
        "primary": f"一般任务；主模型 {labels['primary']}",
        "complex": f"多步推理／架构／深度分析；走 {labels['complex']}",
        "tool_heavy": f"大量工具／终端／改文件；走 {labels['tool_heavy']}",
        "long_context": f"长上下文／超长粘贴；走 {labels['long_context']}",
    }
    state = (
        f"user_message_summary: {scrub(text, limit=2000)}\n"
        f"tool_need_hint: {meta.get('tool_need') or 'unknown'}\n"
        f"session_approx_tokens: {meta.get('approx_tokens') or 0}\n"
        f"history_turns: {meta.get('history_turns') or 0}\n"
        f"bucket_hint: {meta.get('bucket') or 'none'}\n"
        "Pick the single best routing label for THIS Anthropic Messages turn (Claude Code proxy)."
    )
    questions = {
        "route": Choice(
            instructions=(
                "You are a model router for Claude Code via a local Anthropic-compatible proxy. "
                "Choose exactly one label. Prefer cheap for trivial asks; "
                "complex for deep reasoning; tool_heavy when many tools are needed; "
                "long_context when the session/message is very long; primary otherwise."
            ),
            criteria=criteria,
        )
    }
    model = cfg.jev_model
    with TypeSafeClient(model=model) as client:
        result = client.system_one(state=state, questions=questions, model=model)
    ans = result.choices.get("route")
    label = (ans.choice if ans else None) or "primary"
    if label not in labels:
        label = "primary"
    confidence = float(ans.confidence) if ans and ans.confidence is not None else 0.5
    probs = (
        {k: float(v) for k, v in dict(ans.probabilities).items()}
        if ans and getattr(ans, "probabilities", None) is not None
        else None
    )
    return {
        "label": label,
        "model": labels[label],
        "confidence": confidence,
        "probabilities": probs,
        "fallback": False,
        "reason": "jev_choice",
        "backend": "typesafe",
        "jev_model": getattr(result, "model", None) or model,
    }


def route_turn(
    user_message: str,
    *,
    cfg: RouteConfig | None = None,
    meta: dict[str, Any] | None = None,
    dry_run: bool = False,
    fallback_model: str | None = None,
) -> dict[str, Any]:
    """返回选型；低置信／超时／异常 → fallback_model（默认 primary_model），不阻塞。

    P2-3：调用方应传入客户端请求的 model 作为 fallback_model，禁止无条件塞 deepseek-chat。
    """
    cfg = cfg or load_route_config()
    meta = dict(meta or {})
    primary = (fallback_model or "").strip() or cfg.primary_model
    min_conf = float(cfg.min_confidence)

    if not cfg.enabled:
        return {
            "label": "primary",
            "model": primary,
            "confidence": 1.0,
            "fallback": False,
            "reason": "routing_disabled",
            "backend": "off",
        }

    def _primary_fallback(reason: str, **extra: Any) -> dict[str, Any]:
        out = {
            "label": "primary",
            "model": primary,
            "confidence": float(extra.pop("confidence", 0.0) or 0.0),
            "fallback": True,
            "reason": reason,
            "backend": extra.pop("backend", "typesafe"),
        }
        out.update(extra)
        return out

    def _call() -> dict[str, Any]:
        if cfg.mock:
            return _mock_route(cfg.mock, cfg, user_message, meta)
        if dry_run or not os.environ.get("TYPESAFE_API_KEY"):
            out = _heuristic_route(user_message, cfg, meta)
            # P2-8：无 Key 行为可预期
            out["reason"] = "missing_typesafe_key" if not dry_run else "dry_run_heuristic"
            if dry_run and os.environ.get("TYPESAFE_API_KEY"):
                out["reason"] = "dry_run_heuristic"
            elif dry_run:
                out["reason"] = "dry_run_or_missing_key"
            return out
        return _jev_choice(user_message, cfg, meta)

    try:
        out = call_with_timeout(_call, cfg.timeout_seconds)
    except FuturesTimeout:
        # 超时后 daemon 线程仍可能在后台跑完；不 wait（见 timeouts.py）
        out = _primary_fallback("jev_timeout", backend="typesafe" if not cfg.mock else "mock")
    except Exception as exc:  # noqa: BLE001
        out = _primary_fallback(
            f"jev_error:{type(exc).__name__}",
            backend="typesafe" if not cfg.mock else "mock",
            error=scrub(exc, limit=200),
        )

    if not out.get("fallback") and float(out.get("confidence") or 0) < min_conf:
        out = {
            **out,
            "model": primary,
            "label": "primary",
            "fallback": True,
            "reason": "low_confidence_fallback",
            "original_label": out.get("label"),
            "original_model": out.get("model"),
        }
    elif (
        not out.get("fallback")
        and (fallback_model or "").strip()
        and out.get("label") in cfg.unconfigured_labels
    ):
        out = {
            **out,
            "model": primary,
            "model_source": "client_unconfigured_label",
            "original_model": out.get("model"),
        }
    return out


def extract_user_text(body: dict[str, Any], *, include_system: bool = False) -> str:
    """从 Anthropic Messages 请求体抽用户侧文本摘要。

    P2-8：默认**不含** system（Claude Code 长 system 含大量 tool 字样，会把启发式几乎总判成 tool_heavy）。
    Jev live 路径如需短 system hint，由调用方单独传入。
    """
    parts: list[str] = []
    if include_system:
        system = body.get("system")
        if isinstance(system, str) and system.strip():
            parts.append(system[:200])
        elif isinstance(system, list):
            for block in system:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or "")[:200])
                elif isinstance(block, str):
                    parts.append(block[:200])
    messages = body.get("messages") or []
    if isinstance(messages, list):
        for m in messages:
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "") != "user":
                continue
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text") or ""))
                    elif isinstance(block, str):
                        parts.append(block)
    return "\n".join(p for p in parts if p).strip()


def route_messages_request(
    body: dict[str, Any],
    *,
    cfg: RouteConfig | None = None,
) -> dict[str, Any]:
    """对 /v1/messages body 选型；写事件。

    P2-3：fail-open 回退用客户端请求的 model，缺省再用 primary_model。
    """
    cfg = cfg or load_route_config()
    text = extract_user_text(body, include_system=False)
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    approx = sum(len(str((m or {}).get("content") or "")) for m in messages if isinstance(m, dict))
    client_model = str(body.get("model") or "").strip() or None
    meta = {
        "approx_tokens": approx // 4,
        "history_turns": len(messages),
        "tool_need": "unknown",
    }
    decision = route_turn(text, cfg=cfg, meta=meta, fallback_model=client_model)
    emit(
        cfg.events_path,
        "route_decision",
        decision=decision,
        model_in=body.get("model"),
        model_out=decision.get("model"),
        fallback_used_client_model=bool(decision.get("fallback") and client_model),
    )
    return decision
