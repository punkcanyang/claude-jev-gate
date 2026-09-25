"""事件落盘：只记 digest／decision／confidence／latency／reason；无密钥／完整命令。"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def emit(events_path: Path | str, event_type: str, **payload: Any) -> None:
    """尽力而为：写失败不得影响闸／路由／裁压的判决路径。"""
    try:
        path = Path(events_path).expanduser()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        row = {
            "ts": time.time(),
            "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "type": event_type,
            **payload,
        }
        line = json.dumps(row, ensure_ascii=False, default=str)
        with _lock:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except (OSError, ValueError):
        return
