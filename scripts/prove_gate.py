#!/usr/bin/env python3
"""$0 自检：PermissionRequest 工具闸 mock 矩阵。失败 exit≠0。不打 TypeSafe live。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "bin" / "permission_request.py"
ALLOW_NEEDLE = '"hookEventName":"PermissionRequest"'
ALLOW_BEHAVIOR = '"behavior":"allow"'
FORBIDDEN = ("updatedPermissions", "applyRules", '"always"', "session")

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:240]})
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not ok else ""))


def clear_gate_env() -> None:
    for k in list(os.environ):
        if k.startswith("CLAUDE_JEV_GATE_") or k == "TYPESAFE_API_KEY":
            del os.environ[k]


def set_env(**kv: str | None) -> None:
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def run_hook(payload: dict, env_extra: dict[str, str] | None = None, timeout: float = 30.0) -> tuple[int, str, str, float]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    raw = json.dumps(payload, ensure_ascii=False)
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
        cwd=str(ROOT),
    )
    elapsed = time.monotonic() - t0
    return proc.returncode, proc.stdout, proc.stderr, elapsed


SAMPLE = {
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {
        "command": "curl -H 'Authorization: Bearer tok_abc123XYZ' https://u:hunter2@example.com && ls"
    },
    "session_id": "prove-s1",
}


def is_allow(stdout: str) -> bool:
    s = (stdout or "").strip()
    if not s:
        return False
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return False
    hso = obj.get("hookSpecificOutput") or {}
    if hso.get("hookEventName") != "PermissionRequest":
        return False
    decision = hso.get("decision") or {}
    if decision.get("behavior") != "allow":
        return False
    # 禁止 always / updatedPermissions / applyRules
    blob = json.dumps(obj, ensure_ascii=False)
    for bad in FORBIDDEN:
        if bad in blob:
            return False
    return True


def is_empty(stdout: str) -> bool:
    return (stdout or "").strip() == ""


def main() -> int:
    clear_gate_env()
    events_dir = tempfile.mkdtemp(prefix="claude-jev-gate-prove-")
    events_path = str(Path(events_dir) / "events.jsonl")
    base_env = {"CLAUDE_JEV_GATE_EVENTS_PATH": events_path}

    # 1) default disabled
    code, out, err, _ = run_hook(SAMPLE, base_env)
    check("disabled_default_empty", code == 0 and is_empty(out), f"code={code} out={out!r}")

    # P2-1：仅 MOCK=approve、无 ALLOW_MOCK → 不得 allow-all
    env = {**base_env, "CLAUDE_JEV_GATE_ENABLED": "true", "CLAUDE_JEV_GATE_MOCK": "approve"}
    # 显式清掉 ALLOW_MOCK
    env_no = {**env}
    code, out, err, _ = run_hook(SAMPLE, env_no)
    # subprocess 继承；确保子进程无 ALLOW_MOCK
    code, out, err, _ = run_hook(
        SAMPLE,
        {**base_env, "CLAUDE_JEV_GATE_ENABLED": "true", "CLAUDE_JEV_GATE_MOCK": "approve",
         "CLAUDE_JEV_GATE_ALLOW_MOCK": "0"},
    )
    check("mock_approve_without_allow_mock_passthrough", code == 0 and is_empty(out), f"code={code} out={out!r}")

    # 2) enabled + ALLOW_MOCK + approve → allow
    env = {
        **base_env,
        "CLAUDE_JEV_GATE_ENABLED": "true",
        "CLAUDE_JEV_GATE_MOCK": "approve",
        "CLAUDE_JEV_GATE_ALLOW_MOCK": "1",
    }
    code, out, err, _ = run_hook(SAMPLE, env)
    check("approve_allow_once", code == 0 and is_allow(out), f"code={code} out={out!r}")
    check(
        "approve_no_always_fields",
        code == 0 and is_allow(out) and all(b not in out for b in FORBIDDEN),
        out,
    )

    # 3-8 matrix → passthrough
    for kind in ("deny", "unsure", "low_confidence", "error", "malformed"):
        env = {
            **base_env,
            "CLAUDE_JEV_GATE_ENABLED": "true",
            "CLAUDE_JEV_GATE_MOCK": kind,
            "CLAUDE_JEV_GATE_ALLOW_MOCK": "1",
            "CLAUDE_JEV_GATE_TIMEOUT_SECONDS": "3",
        }
        code, out, err, elapsed = run_hook(SAMPLE, env, timeout=20.0)
        check(
            f"mock_{kind}_passthrough",
            code == 0 and is_empty(out),
            f"code={code} out={out!r} elapsed={elapsed:.2f}",
        )

    # dangerous tail beyond what Jev can see → never auto-allow
    long_cmd = {"command": "echo " + "A" * 5000 + " && rm -rf ~"}
    env = {
        **base_env,
        "CLAUDE_JEV_GATE_ENABLED": "true",
        "CLAUDE_JEV_GATE_MOCK": "approve",
        "CLAUDE_JEV_GATE_ALLOW_MOCK": "1",
    }
    code, out, err, _ = run_hook({**SAMPLE, "tool_input": long_cmd}, env)
    check("truncated_input_passthrough", code == 0 and is_empty(out), f"code={code} out={out!r}")

    # timeout: wall clock roughly at timeout budget, not hang forever
    env = {
        **base_env,
        "CLAUDE_JEV_GATE_ENABLED": "true",
        "CLAUDE_JEV_GATE_MOCK": "timeout",
        "CLAUDE_JEV_GATE_ALLOW_MOCK": "1",
        "CLAUDE_JEV_GATE_TIMEOUT_SECONDS": "1.0",
    }
    code, out, err, elapsed = run_hook(SAMPLE, env, timeout=20.0)
    check(
        "mock_timeout_passthrough",
        code == 0 and is_empty(out),
        f"code={code} out={out!r} elapsed={elapsed:.2f}",
    )
    check(
        "mock_timeout_returns_promptly",
        0.8 <= elapsed <= 5.0,
        f"elapsed={elapsed:.2f}s (want ~1s, <5s)",
    )

    # 9) enabled, no mock, no key → passthrough
    clear_gate_env()
    env = {"CLAUDE_JEV_GATE_ENABLED": "true", "CLAUDE_JEV_GATE_EVENTS_PATH": events_path}
    # ensure no key
    env.pop("TYPESAFE_API_KEY", None)
    os.environ.pop("TYPESAFE_API_KEY", None)
    code, out, err, _ = run_hook(SAMPLE, env)
    check("enabled_no_key_passthrough", code == 0 and is_empty(out), f"code={code} out={out!r}")

    # 10) events scrub: no raw bearer / hunter2
    secret_bits = ("tok_abc123XYZ", "hunter2", "Bearer tok")
    log_text = ""
    ep = Path(events_path)
    if ep.is_file():
        log_text = ep.read_text(encoding="utf-8")
    leaked = [s for s in secret_bits if s in log_text]
    check("events_no_secrets", not leaked, f"leaked={leaked}")

    # events should have digest/outcome lines after enabled runs
    check("events_file_written", ep.is_file() and ep.stat().st_size > 0, events_path)

    failed = [r for r in RESULTS if not r["ok"]]
    print("---")
    print(f"passed={len(RESULTS) - len(failed)} failed={len(failed)} total={len(RESULTS)}")
    if failed:
        for r in failed:
            print(f"  FAIL {r['name']}: {r['detail']}")
        return 1
    print("prove_gate: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
