#!/usr/bin/env python3
"""≥20 条标注样本路由证明：选型分布 + 兜底主模型；失败 exit≠0。"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claude_jev_gate.config import RouteConfig  # noqa: E402
from claude_jev_gate.routing import route_turn  # noqa: E402

SAMPLES = ROOT / "data" / "routing_samples.jsonl"
# P2-11：报告写到临时目录，勿改写已跟踪的 notes/reports


def _base_cfg(events: Path) -> RouteConfig:
    return RouteConfig(
        enabled=True,
        min_confidence=0.55,
        timeout_seconds=2.0,
        mock="heuristic",
        jev_model="jev-latest",
        primary_model="deepseek-chat",
        models={
            "cheap": "deepseek-chat",
            "primary": "deepseek-chat",
            "complex": "deepseek-reasoner",
            "tool_heavy": "deepseek-reasoner",
            "long_context": "deepseek-reasoner",
        },
        events_path=events,
    )


def main() -> int:
    failures: list[str] = []
    rows = [json.loads(l) for l in SAMPLES.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(rows) < 20:
        failures.append(f"need >=20 samples, got {len(rows)}")

    with tempfile.TemporaryDirectory() as td:
        events = Path(td) / "events.jsonl"
        cfg = _base_cfg(events)
        results = []
        for row in rows:
            meta = {"bucket": row.get("bucket"), "approx_tokens": len(row.get("text") or "") // 4}
            decision = route_turn(row["text"], cfg=cfg, meta=meta, dry_run=True)
            expect = row.get("expect_label")
            match = decision.get("label") == expect
            results.append(
                {
                    "id": row["id"],
                    "bucket": row.get("bucket"),
                    "expect_label": expect,
                    "got_label": decision.get("label"),
                    "got_model": decision.get("model"),
                    "confidence": decision.get("confidence"),
                    "fallback": decision.get("fallback"),
                    "reason": decision.get("reason"),
                    "backend": decision.get("backend"),
                    "match": match,
                }
            )

        by_label = Counter(r["got_label"] for r in results)
        hard = sum(1 for r in results if r["match"])
        n = len(results)

        if len(by_label) < 2:
            failures.append(f"label distribution too narrow: {dict(by_label)}")
        if hard < max(10, n // 2):
            failures.append(f"hard_match too low: {hard}/{n}")

        cfg_off = replace(cfg, enabled=False)
        off_labels = {
            route_turn(r["text"], cfg=cfg_off, meta={"bucket": r.get("bucket")}).get("label") for r in rows
        }
        if off_labels != {"primary"}:
            failures.append(f"routing disabled should be all primary, got {off_labels}")

        low = route_turn("ping", cfg=replace(cfg, mock="low_confidence"), meta={"bucket": "simple"})
        if not (
            low.get("fallback")
            and low.get("model") == cfg.primary_model
            and low.get("reason") == "low_confidence_fallback"
        ):
            failures.append(f"low_confidence fallback failed: {low}")

        to = route_turn("ping", cfg=replace(cfg, mock="timeout", timeout_seconds=0.3))
        if not (to.get("fallback") and to.get("model") == cfg.primary_model and to.get("reason") == "jev_timeout"):
            failures.append(f"timeout fallback failed: {to}")

        err = route_turn("ping", cfg=replace(cfg, mock="error"))
        if not (
            err.get("fallback")
            and err.get("model") == cfg.primary_model
            and str(err.get("reason") or "").startswith("jev_error")
        ):
            failures.append(f"error fallback failed: {err}")

        lab = route_turn("x", cfg=replace(cfg, mock="label:complex"))
        if lab.get("label") != "complex" or lab.get("fallback"):
            failures.append(f"label:complex mock failed: {lab}")


        # P2-3：fallback 用客户端 model，不是无条件 primary_model
        fb = route_turn(
            "ping",
            cfg=replace(cfg, mock="error"),
            fallback_model="claude-sonnet-4-5",
        )
        if not (fb.get("fallback") and fb.get("model") == "claude-sonnet-4-5"):
            failures.append(f"P2-3 client model fallback failed: {fb}")

        # P2-8：长 system 含 tool 字样 + 短 user「你好」→ 不应判 tool_heavy
        from claude_jev_gate.routing import extract_user_text, route_messages_request
        long_system = (
            "You are Claude Code. You have tools: Bash, Read, Grep, patch files, run pytest in shell. "
            * 40
        )
        body = {
            "model": "claude-sonnet-4-5",
            "system": long_system,
            "messages": [{"role": "user", "content": "你好"}],
        }
        # extract should not include system by default
        ut = extract_user_text(body, include_system=False)
        if "Bash" in ut or "pytest" in ut:
            failures.append(f"P2-8 extract_user_text leaked system: {ut[:80]!r}")
        decision = route_messages_request(body, cfg=cfg)
        if decision.get("label") == "tool_heavy":
            failures.append(f"P2-8 long system caused tool_heavy: {decision}")

        report = {
            "n": n,
            "hard_match": hard,
            "hard_match_rate": hard / n if n else 0,
            "label_distribution": dict(by_label),
            "fallback_count": sum(1 for r in results if r["fallback"]),
            "routing_disabled_labels": sorted(off_labels),
            "low_confidence": low,
            "timeout": {k: to.get(k) for k in ("label", "model", "fallback", "reason")},
            "error": {k: err.get(k) for k in ("label", "model", "fallback", "reason")},
            "failures": failures,
            "results": results,
        }
        out_dir = Path(td) / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        OUT_JSON = out_dir / "routing-prove.json"
        OUT_MD = out_dir / "routing-prove.md"
        OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            "# 路由证明（claude-jev-gate）",
            "",
            f"- 样本数：{n}",
            f"- 硬一致：{hard}/{n} = {report['hard_match_rate']:.1%}",
            f"- 选型分布：{dict(by_label)}",
            f"- 关路由 labels：{sorted(off_labels)}",
            f"- failures：{failures or 'none'}",
            "",
            "| id | bucket | expect | got | model | conf | fallback | match |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in results:
            lines.append(
                f"| {r['id']} | {r['bucket']} | {r['expect_label']} | {r['got_label']} | "
                f"`{r['got_model']}` | {float(r['confidence'] or 0):.2f} | {r['fallback']} | "
                f"{'Y' if r['match'] else 'N'} |"
            )
        OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if failures:
        print("prove_routing: FAIL")
        for f in failures:
            print(" -", f)
        print("wrote", OUT_MD)
        return 1
    print(
        json.dumps(
            {k: report[k] for k in ("n", "hard_match_rate", "label_distribution")},
            ensure_ascii=False,
        )
    )
    print("prove_routing: ALL GREEN")
    print("wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
