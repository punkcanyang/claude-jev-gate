"""环境变量配置：闸／路由／裁压三开关默认关；TypeSafe 路径 insert(0)。"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


MIN_CONFIDENCE_FLOOR = 0.5
DEFAULT_MIN_CONFIDENCE = 0.80
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_ROUTE_MIN_CONFIDENCE = 0.55
DEFAULT_TRIM_KEEP_LAST_N = 6
DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 8787
DEFAULT_PRIMARY_MODEL = "deepseek-chat"
DEFAULT_COMPRESS_MIN_MESSAGES = 8
DEFAULT_COMPRESS_MIN_CHARS = 8000
DEFAULT_PROXY_MAX_BODY_BYTES = 32 * 1024 * 1024  # 32 MiB

_FALSEY = frozenset({"", "0", "false", "no", "off", "n", "disabled"})
_TRUTHY = frozenset({"1", "true", "yes", "on", "y", "enabled"})

ROUTE_LABELS = ("cheap", "primary", "complex", "tool_heavy", "long_context")


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in _FALSEY:
        return False
    if s in _TRUTHY:
        return True
    return default


def _typesafe_site_dirs() -> list[Path]:
    """typesafe_sdk 不在当前解释器时，从环境变量补路径。"""
    dirs: list[Path] = []
    explicit = os.environ.get("CLAUDE_JEV_GATE_TYPESAFE_SITE_PACKAGES", "").strip()
    if explicit:
        dirs.extend(Path(p).expanduser() for p in explicit.split(os.pathsep) if p.strip())
    venv = os.environ.get("CLAUDE_JEV_GATE_TYPESAFE_VENV", "").strip()
    if not venv:
        # 本仓默认：box 上 typesafe-venv（文档写死；无则跳过）
        default_venv = Path("/workspace/tools/typesafe-venv")
        if default_venv.is_dir():
            venv = str(default_venv)
    if venv:
        ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        dirs.append(Path(venv).expanduser() / "lib" / ver / "site-packages")
    return [d for d in dirs if d.is_dir()]


def ensure_typesafe_path() -> None:
    """insert(0)：本仓优先 site-packages，避免系统旧 typing_extensions 抢先。"""
    for d in _typesafe_site_dirs():
        p = str(d)
        if p in sys.path:
            try:
                sys.path.remove(p)
            except ValueError:
                pass
        sys.path.insert(0, p)


@dataclass(frozen=True)
class GateConfig:
    enabled: bool
    min_confidence: float
    timeout_seconds: float
    mock: str
    allow_mock: bool
    jev_model: str
    events_path: Path


@dataclass(frozen=True)
class RouteConfig:
    enabled: bool
    min_confidence: float
    timeout_seconds: float
    mock: str
    jev_model: str
    primary_model: str
    models: dict[str, str] = field(default_factory=dict)
    events_path: Path = field(default_factory=lambda: Path.home() / ".claude" / "claude-jev-gate" / "events.jsonl")
    # 模型只来自内置默认（未配 env）的 label：有客户端 model 时用客户端 model，避免把 deepseek-chat 发给别家上游
    unconfigured_labels: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TrimCompressConfig:
    enabled: bool
    keep_last_n_turns: int
    drop_old_tool_noise: bool
    compress_min_messages: int
    compress_min_chars: int
    events_path: Path


@dataclass(frozen=True)
class ProxyConfig:
    host: str
    port: int
    upstream_base_url: str
    upstream_api_key: str
    upstream_mock: bool
    auth_token: str
    max_body_bytes: int
    route: RouteConfig
    trim_compress: TrimCompressConfig


def _events_path() -> Path:
    events_raw = (os.environ.get("CLAUDE_JEV_GATE_EVENTS_PATH") or "").strip()
    if events_raw:
        return Path(events_raw).expanduser()
    return Path.home() / ".claude" / "claude-jev-gate" / "events.jsonl"


def load_config() -> GateConfig:
    enabled = as_bool(os.environ.get("CLAUDE_JEV_GATE_ENABLED"), False)
    try:
        min_conf = float(os.environ.get("CLAUDE_JEV_GATE_MIN_CONFIDENCE") or DEFAULT_MIN_CONFIDENCE)
    except (TypeError, ValueError):
        min_conf = DEFAULT_MIN_CONFIDENCE
    min_conf = max(min_conf, MIN_CONFIDENCE_FLOOR)
    try:
        timeout = float(os.environ.get("CLAUDE_JEV_GATE_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    timeout = max(timeout, 0.1)
    mock = (os.environ.get("CLAUDE_JEV_GATE_MOCK") or "").strip()
    # P2-1：mock 须额外显式测试开关，否则忽略 MOCK（防生产误开全放行）
    allow_mock = as_bool(os.environ.get("CLAUDE_JEV_GATE_ALLOW_MOCK"), False)
    jev_model = (os.environ.get("CLAUDE_JEV_GATE_JEV_MODEL") or "jev-latest").strip() or "jev-latest"
    return GateConfig(
        enabled=enabled,
        min_confidence=min_conf,
        timeout_seconds=timeout,
        mock=mock,
        allow_mock=allow_mock,
        jev_model=jev_model,
        events_path=_events_path(),
    )


_LABEL_MODEL_ENV = {
    "cheap": "CLAUDE_JEV_MODEL_CHEAP",
    "complex": "CLAUDE_JEV_MODEL_COMPLEX",
    "tool_heavy": "CLAUDE_JEV_MODEL_TOOL_HEAVY",
    "long_context": "CLAUDE_JEV_MODEL_LONG_CONTEXT",
}


def unconfigured_route_labels() -> frozenset[str]:
    if (os.environ.get("CLAUDE_JEV_PRIMARY_MODEL") or "").strip():
        return frozenset()
    return frozenset(
        {"primary"}
        | {label for label, env in _LABEL_MODEL_ENV.items() if not (os.environ.get(env) or "").strip()}
    )


def candidate_labels(primary: str | None = None) -> dict[str, str]:
    primary_model = (primary or os.environ.get("CLAUDE_JEV_PRIMARY_MODEL") or DEFAULT_PRIMARY_MODEL).strip()
    return {
        "cheap": (os.environ.get("CLAUDE_JEV_MODEL_CHEAP") or primary_model).strip() or primary_model,
        "primary": primary_model,
        "complex": (os.environ.get("CLAUDE_JEV_MODEL_COMPLEX") or primary_model).strip() or primary_model,
        "tool_heavy": (os.environ.get("CLAUDE_JEV_MODEL_TOOL_HEAVY") or primary_model).strip() or primary_model,
        "long_context": (os.environ.get("CLAUDE_JEV_MODEL_LONG_CONTEXT") or primary_model).strip() or primary_model,
    }


def load_route_config() -> RouteConfig:
    enabled = as_bool(os.environ.get("CLAUDE_JEV_ROUTE_ENABLED"), False)
    try:
        min_conf = float(os.environ.get("CLAUDE_JEV_ROUTE_MIN_CONFIDENCE") or DEFAULT_ROUTE_MIN_CONFIDENCE)
    except (TypeError, ValueError):
        min_conf = DEFAULT_ROUTE_MIN_CONFIDENCE
    min_conf = max(0.0, min(1.0, min_conf))
    try:
        timeout = float(
            os.environ.get("CLAUDE_JEV_ROUTE_TIMEOUT_SECONDS")
            or os.environ.get("CLAUDE_JEV_GATE_TIMEOUT_SECONDS")
            or DEFAULT_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    timeout = max(timeout, 0.1)
    mock = (os.environ.get("CLAUDE_JEV_ROUTE_MOCK") or "").strip()
    jev_model = (
        os.environ.get("CLAUDE_JEV_ROUTE_JEV_MODEL")
        or os.environ.get("CLAUDE_JEV_GATE_JEV_MODEL")
        or "jev-latest"
    ).strip() or "jev-latest"
    primary = (os.environ.get("CLAUDE_JEV_PRIMARY_MODEL") or DEFAULT_PRIMARY_MODEL).strip() or DEFAULT_PRIMARY_MODEL
    models = candidate_labels(primary)
    return RouteConfig(
        enabled=enabled,
        min_confidence=min_conf,
        timeout_seconds=timeout,
        mock=mock,
        jev_model=jev_model,
        primary_model=primary,
        models=models,
        events_path=_events_path(),
        unconfigured_labels=unconfigured_route_labels(),
    )


def load_trim_compress_config() -> TrimCompressConfig:
    enabled = as_bool(os.environ.get("CLAUDE_JEV_TRIM_COMPRESS_ENABLED"), False)
    try:
        keep_n = int(os.environ.get("CLAUDE_JEV_TRIM_KEEP_LAST_N") or DEFAULT_TRIM_KEEP_LAST_N)
    except (TypeError, ValueError):
        keep_n = DEFAULT_TRIM_KEEP_LAST_N
    keep_n = max(1, keep_n)
    drop_noise = as_bool(os.environ.get("CLAUDE_JEV_TRIM_DROP_OLD_TOOL_NOISE"), True)
    try:
        min_msgs = int(os.environ.get("CLAUDE_JEV_COMPRESS_MIN_MESSAGES") or DEFAULT_COMPRESS_MIN_MESSAGES)
    except (TypeError, ValueError):
        min_msgs = DEFAULT_COMPRESS_MIN_MESSAGES
    min_msgs = max(1, min_msgs)
    try:
        min_chars = int(os.environ.get("CLAUDE_JEV_COMPRESS_MIN_CHARS") or DEFAULT_COMPRESS_MIN_CHARS)
    except (TypeError, ValueError):
        min_chars = DEFAULT_COMPRESS_MIN_CHARS
    min_chars = max(0, min_chars)
    return TrimCompressConfig(
        enabled=enabled,
        keep_last_n_turns=keep_n,
        drop_old_tool_noise=drop_noise,
        compress_min_messages=min_msgs,
        compress_min_chars=min_chars,
        events_path=_events_path(),
    )


def resolve_upstream_api_key(upstream_base_url: str) -> str:
    """P2-2：按上游选 Key，避免 Anthropic Key 误发给 DeepSeek。

    优先级：
    1. CLAUDE_JEV_UPSTREAM_API_KEY（显式上游专用）
    2. host 含 deepseek → 仅 DEEPSEEK_API_KEY
    3. host 含 anthropic → 仅 ANTHROPIC_API_KEY
    4. 其它未知 host → 不自动回退（空，除非设了 UPSTREAM_API_KEY）
    """
    explicit = (os.environ.get("CLAUDE_JEV_UPSTREAM_API_KEY") or "").strip()
    if explicit:
        return explicit
    host = ""
    try:
        host = (urlparse(upstream_base_url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        host = ""
    if "deepseek" in host:
        return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if "anthropic" in host:
        return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    # 未知上游：不猜测，避免串 Key
    return ""


def load_proxy_config() -> ProxyConfig:
    host = (os.environ.get("CLAUDE_JEV_PROXY_HOST") or DEFAULT_PROXY_HOST).strip() or DEFAULT_PROXY_HOST
    try:
        port = int(os.environ.get("CLAUDE_JEV_PROXY_PORT") or DEFAULT_PROXY_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_PROXY_PORT
    upstream = (os.environ.get("CLAUDE_JEV_UPSTREAM_BASE_URL") or "").strip().rstrip("/")
    key = resolve_upstream_api_key(upstream)
    upstream_mock = as_bool(os.environ.get("CLAUDE_JEV_UPSTREAM_MOCK"), False)
    auth_token = (os.environ.get("CLAUDE_JEV_PROXY_AUTH_TOKEN") or "").strip()
    try:
        max_body = int(os.environ.get("CLAUDE_JEV_PROXY_MAX_BODY_BYTES") or DEFAULT_PROXY_MAX_BODY_BYTES)
    except (TypeError, ValueError):
        max_body = DEFAULT_PROXY_MAX_BODY_BYTES
    max_body = max(1024, max_body)
    return ProxyConfig(
        host=host,
        port=port,
        upstream_base_url=upstream,
        upstream_api_key=key,
        upstream_mock=upstream_mock,
        auth_token=auth_token,
        max_body_bytes=max_body,
        route=load_route_config(),
        trim_compress=load_trim_compress_config(),
    )
