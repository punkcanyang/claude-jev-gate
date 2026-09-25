"""环境变量配置：默认关；置信门槛；超时；mock；TypeSafe 路径。"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MIN_CONFIDENCE_FLOOR = 0.5
DEFAULT_MIN_CONFIDENCE = 0.80
DEFAULT_TIMEOUT_SECONDS = 8.0

_FALSEY = frozenset({"", "0", "false", "no", "off", "n", "disabled"})
_TRUTHY = frozenset({"1", "true", "yes", "on", "y", "enabled"})


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
    """typesafe_sdk 不在当前解释器时，从环境变量补路径（借鉴 hermes 行为，不共用仓）。"""
    dirs: list[Path] = []
    explicit = os.environ.get("CLAUDE_JEV_GATE_TYPESAFE_SITE_PACKAGES", "").strip()
    if explicit:
        dirs.extend(Path(p).expanduser() for p in explicit.split(os.pathsep) if p.strip())
    venv = os.environ.get("CLAUDE_JEV_GATE_TYPESAFE_VENV", "").strip()
    if venv:
        ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        dirs.append(Path(venv).expanduser() / "lib" / ver / "site-packages")
    return [d for d in dirs if d.is_dir()]


def ensure_typesafe_path() -> None:
    # append 而非 insert(0)：不遮蔽本仓依赖
    for d in _typesafe_site_dirs():
        p = str(d)
        if p not in sys.path:
            sys.path.append(p)


@dataclass(frozen=True)
class GateConfig:
    enabled: bool
    min_confidence: float
    timeout_seconds: float
    mock: str
    jev_model: str
    events_path: Path


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
    jev_model = (os.environ.get("CLAUDE_JEV_GATE_JEV_MODEL") or "jev-latest").strip() or "jev-latest"
    events_raw = (os.environ.get("CLAUDE_JEV_GATE_EVENTS_PATH") or "").strip()
    if events_raw:
        events_path = Path(events_raw).expanduser()
    else:
        events_path = Path.home() / ".claude" / "claude-jev-gate" / "events.jsonl"
    return GateConfig(
        enabled=enabled,
        min_confidence=min_conf,
        timeout_seconds=timeout,
        mock=mock,
        jev_model=jev_model,
        events_path=events_path,
    )
