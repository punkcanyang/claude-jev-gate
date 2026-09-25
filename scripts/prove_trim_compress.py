#!/usr/bin/env python3
"""构造超长会话，证明 compress 管线顺序为 trim → compress。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claude_jev_gate.config import TrimCompressConfig  # noqa: E402
from claude_jev_gate.pipeline import apply_trim_then_compress, get_last_pipeline  # noqa: E402
from claude_jev_gate.trim import estimate_chars  # noqa: E402

OUT_MD = ROOT / "notes" / "reports" / "trim-compress-proof.md"
OUT_JSON = ROOT / "notes" / "reports" / "trim-compress-proof.json"


def build_long_session(n_turns: int = 40) -> list[dict]:
    msgs = [{"role": "system", "content": "你是 Claude Code 助手。系统约束：勿泄露密钥。"}]
    for i in range(n_turns):
        msgs.append({"role": "user", "content": f"用户轮 {i}: 请继续处理任务 {i}."})
        msgs.append(
            {
                "role": "assistant",
                "content": f"助手轮 {i}: 调用工具中…",
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {"name": "Bash", "arguments": "{}"},
                    }
                ],
            }
        )
        msgs.append(
            {
                "role": "tool",
                "tool_call_id": f"c{i}",
                "content": ("工具噪声输出 " + ("x" * 200) + f" turn={i}\n") * 5,
            }
        )
    return msgs


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        events_path = Path(td) / "events.jsonl"
        cfg = TrimCompressConfig(
            enabled=True,
            keep_last_n_turns=6,
            drop_old_tool_noise=True,
            events_path=events_path,
        )
        msgs = build_long_session(40)
        chars_in = estimate_chars(msgs)
        out, pipeline = apply_trim_then_compress(msgs, cfg=cfg, focus_topic="prove")
        chars_out = estimate_chars(out)

        events = []
        if events_path.is_file():
            events = [json.loads(l) for l in events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        types = [e.get("type") for e in events]

        order_ok = False
        if "trim" in types and "compress" in types:
            order_ok = types.index("trim") < types.index("compress")
        if len(pipeline) >= 2:
            order_ok = order_ok or (
                str(pipeline[0].get("step", "")).startswith("trim")
                and pipeline[1].get("step") == "compress"
            )
        if not order_ok:
            failures.append(f"order not trim→compress: types={types} pipeline={pipeline}")

        if chars_out >= chars_in:
            failures.append(f"expected shorter chars: in={chars_in} out={chars_out}")
        if len(out) >= len(msgs):
            failures.append(f"expected fewer messages: in={len(msgs)} out={len(out)}")

        cfg_off = TrimCompressConfig(
            enabled=False,
            keep_last_n_turns=6,
            drop_old_tool_noise=True,
            events_path=Path(td) / "off.jsonl",
        )
        out_off, pipe_off = apply_trim_then_compress(msgs, cfg=cfg_off)
        if pipe_off:
            failures.append(f"disabled should skip pipeline, got {pipe_off}")
        if len(out_off) != len(msgs):
            failures.append("disabled should return same message count")

        out_force, pipe_force = apply_trim_then_compress(msgs, cfg=cfg_off, force=True)
        if not (
            len(pipe_force) >= 2
            and str(pipe_force[0].get("step", "")).startswith("trim")
            and pipe_force[1].get("step") == "compress"
        ):
            failures.append(f"force pipeline order bad: {pipe_force}")

        last = get_last_pipeline()
        report = {
            "order_ok": order_ok,
            "pipeline": pipeline,
            "event_types": types,
            "messages_in": len(msgs),
            "messages_out": len(out),
            "chars_in": chars_in,
            "chars_out": chars_out,
            "disabled_pipeline": pipe_off,
            "force_pipeline": pipe_force,
            "last_pipeline": last,
            "failures": failures,
        }
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# trim → compress 证明（claude-jev-gate）",
            "",
            f"- order_ok：**{order_ok}**",
            f"- 输入消息数：{len(msgs)} → 输出：{len(out)}",
            f"- chars：{chars_in} → {chars_out}",
            f"- 事件类型顺序：{types}",
            f"- failures：{failures or 'none'}",
            "",
            "## 管线",
            "",
            "```json",
            json.dumps(pipeline, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
        OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    if failures:
        print("prove_trim_compress: FAIL")
        for f in failures:
            print(" -", f)
        print("wrote", OUT_MD)
        return 1
    print(
        json.dumps(
            {
                "order_ok": True,
                "messages_in": len(msgs),
                "messages_out": len(out),
                "chars_in": chars_in,
                "chars_out": chars_out,
            },
            ensure_ascii=False,
        )
    )
    print("prove_trim_compress: ALL GREEN")
    print("wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
