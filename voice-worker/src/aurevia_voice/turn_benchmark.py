"""WP-10.4 turn-handling benchmark: run the simulator several times for one worker setting.

The worker must already be running with the setting under test (endpointing, preemptive
generation, Deepgram key terms); restart it between settings. Each simulated call uses real
speech services, so runs are paced and the benchmark stops at the first failed call rather
than retrying (a quota or credit problem must not be hammered).

    python -m aurevia_voice.turn_benchmark --label fixed-0.5 --runs 5 \\
        --scenarios busy skeptical --email ... --password ... --out results.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

KEY_TERMS = ("aurevia", "meera", "priyanka")


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def summarize(label: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """One setting's numbers across its runs. Failed runs are counted, never averaged in."""
    ok = [r for r in runs if r.get("status") == "completed" and r.get("latency")]

    def field(name: str) -> list[float]:
        return [float(r["latency"][name]) for r in ok if r["latency"].get(name) is not None]

    names = [r for r in ok if r.get("scenario") == "names"]
    heard = " ".join(str(r.get("heard", "")).lower() for r in names)
    return {
        "label": label,
        "runs": len(runs),
        "completed": len(ok),
        "failed": len(runs) - len(ok),
        "e2e_p50_ms_median": _median(field("e2e_p50_ms")),
        "e2e_p95_ms_median": _median(field("e2e_p95_ms")),
        "end_of_turn_delay_p50_ms_median": _median(field("end_of_turn_delay_p50_ms")),
        "tts_ttfb_p50_ms_median": _median(field("tts_ttfb_p50_ms")),
        "llm_ttft_p50_ms_median": _median(field("llm_ttft_p50_ms")),
        "interrupted_turns_total": int(sum(field("interrupted_turns"))),
        "measured_turns_total": int(sum(field("measured_turns"))),
        "prospect_wer_mean": (
            round(statistics.mean(w), 3)
            if (w := [float(r["prospect_wer"]) for r in ok if r.get("prospect_wer") is not None])
            else None
        ),
        "key_term_hits": {t: heard.count(t) for t in KEY_TERMS} if names else None,
    }


def run_once(args: argparse.Namespace, scenario: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        command = [
            sys.executable,
            "-m",
            "aurevia_voice.simulate",
            "--email",
            args.email,
            "--password",
            args.password,
            "--scenario",
            scenario,
            "--json-out",
            str(out),
        ]
        try:
            subprocess.run(command, timeout=args.timeout, check=False, capture_output=True)  # noqa: S603
        except subprocess.TimeoutExpired:
            return {"scenario": scenario, "status": "timeout"}
        if not out.exists():
            return {"scenario": scenario, "status": "no_result"}
        result: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurevia_voice.turn_benchmark")
    parser.add_argument("--label", required=True, help="the worker setting under test")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--scenarios", nargs="+", default=["busy", "skeptical"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--pause", type=float, default=5.0, help="seconds between calls")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--out", required=True, help="JSON file: runs and summary")
    args = parser.parse_args(argv)

    runs: list[dict[str, Any]] = []
    stopped = None
    for index in range(args.runs):
        for scenario in args.scenarios:
            result = run_once(args, scenario)
            runs.append(result)
            print(f"[{args.label}] run {index + 1} {scenario}: {result.get('status')}", flush=True)
            if result.get("status") != "completed":
                stopped = f"run {index + 1} {scenario}: {result.get('status')}"
                break
            time.sleep(args.pause)
        if stopped:
            break
    summary = summarize(args.label, runs)
    summary["stopped_at"] = stopped
    Path(args.out).write_text(
        json.dumps({"summary": summary, "runs": runs}, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
