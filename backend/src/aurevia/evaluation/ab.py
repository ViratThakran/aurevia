"""Simulator A/B for playbooks (WP-12.8, built early; tested with fakes only).

    python -m aurevia.evaluation.ab --candidate seed [--baseline none|FILE] [--repeat 3]
        [--only NAME ...] [--report ab.json]

Runs the sales scenarios twice in one throwaway workspace: first with the baseline (no
playbook, or the entries in FILE), then with the candidate playbook active. Entries come from a
JSON file in the seed format (``{"entries": [...]}``), or ``seed`` for the built-in seed
entries. In the throwaway workspace every entry is approved so it can be offered; that approval
never touches a real workspace.

The rule from the plan: **only an improvement with no regression can become active.**

- A regression is any scenario that passes less often with the candidate, or a style measure
  (long replies, stacked questions, stock openers, repeated openers, fillers, repeated
  reactions) that gets worse by more than its tolerance.
- An improvement is any scenario that passes more often, or a style measure that gets better by
  more than its tolerance.

A real result needs the real model (the paid key): one run each is noisy, so use ``--repeat``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aurevia.evaluation.run import run_scenario, throwaway_owner
from aurevia.evaluation.scenarios import SCENARIOS, Scenario, ScenarioResult
from aurevia.evaluation.style import measure
from aurevia.providers.fakes import FakeVoiceTransport

# Style measures where lower is better, with how much change counts (absolute).
STYLE_TOLERANCE = {
    "long_reply_rate": 0.05,
    "multi_question_rate": 0.05,
    "stock_opener_rate": 0.05,
    "repeated_opener_rate": 0.05,
    "fillers_per_reply": 0.1,
    "repeated_reaction_rate": 0.05,
}


@dataclass
class Arm:
    name: str
    playbook_version_id: str | None
    # One list of results per repeat.
    runs: list[list[ScenarioResult]] = field(default_factory=list)

    def pass_rates(self) -> dict[str, float]:
        totals: dict[str, list[bool]] = {}
        for run in self.runs:
            for result in run:
                totals.setdefault(result.name, []).append(result.passed)
        return {name: sum(passes) / len(passes) for name, passes in totals.items()}

    def style(self) -> dict[str, float]:
        return measure([r.replies for run in self.runs for r in run]).as_dict()


@dataclass
class Verdict:
    improvements: list[str]
    regressions: list[str]

    @property
    def can_become_active(self) -> bool:
        return bool(self.improvements) and not self.regressions


def compare(baseline: Arm, candidate: Arm) -> Verdict:
    improvements: list[str] = []
    regressions: list[str] = []
    before, after = baseline.pass_rates(), candidate.pass_rates()
    for name in sorted(set(before) | set(after)):
        b, c = before.get(name, 0.0), after.get(name, 0.0)
        if c > b:
            improvements.append(f"{name}: passes {b:.0%} -> {c:.0%}")
        elif c < b:
            regressions.append(f"{name}: passes {b:.0%} -> {c:.0%}")
    style_b, style_c = baseline.style(), candidate.style()
    for metric, tolerance in STYLE_TOLERANCE.items():
        delta = style_c.get(metric, 0.0) - style_b.get(metric, 0.0)
        if delta > tolerance:
            regressions.append(f"{metric}: {style_b[metric]} -> {style_c[metric]}")
        elif delta < -tolerance:
            improvements.append(f"{metric}: {style_b[metric]} -> {style_c[metric]}")
    return Verdict(improvements=improvements, regressions=regressions)


def activate_entries(client: TestClient, owner: dict[str, str], entries: Sequence[Any]) -> str:
    """Create, approve and activate a playbook in the throwaway workspace. Returns its id."""
    agent_id = client.get("/api/v1/agents/default", headers=owner).json()["id"]
    draft = client.post("/api/v1/playbooks", json={"agent_id": agent_id}, headers=owner)
    draft.raise_for_status()
    version_id: str = draft.json()["id"]
    for entry in entries:
        added = client.post(f"/api/v1/playbooks/{version_id}/entries", json=entry, headers=owner)
        added.raise_for_status()
        client.post(
            f"/api/v1/playbooks/{version_id}/entries/{added.json()['id']}/approve",
            headers=owner,
        ).raise_for_status()
    client.post(f"/api/v1/playbooks/{version_id}/activate", headers=owner).raise_for_status()
    return version_id


def retire_active(client: TestClient, owner: dict[str, str]) -> None:
    for version in client.get("/api/v1/playbooks", headers=owner).json():
        if version["status"] == "active":
            client.post(f"/api/v1/playbooks/{version['id']}/retire", headers=owner)


def run_arm(
    client: TestClient,
    transport: FakeVoiceTransport,
    owner: dict[str, str],
    arm: Arm,
    scenarios: Sequence[Scenario],
    repeat: int,
) -> Arm:
    for _ in range(repeat):
        arm.runs.append([run_scenario(client, transport, owner, s) for s in scenarios])
    return arm


def run_ab(
    client: TestClient,
    transport: FakeVoiceTransport,
    *,
    baseline_entries: Sequence[Any] | None,
    candidate_entries: Sequence[Any],
    scenarios: Sequence[Scenario] = SCENARIOS,
    repeat: int = 1,
) -> tuple[Arm, Arm, Verdict]:
    """Both arms in one throwaway workspace: the baseline first, then the candidate."""
    owner = throwaway_owner(client)
    baseline_id = activate_entries(client, owner, baseline_entries) if baseline_entries else None
    baseline = run_arm(client, transport, owner, Arm("baseline", baseline_id), scenarios, repeat)
    retire_active(client, owner)
    candidate_id = activate_entries(client, owner, candidate_entries)
    candidate = run_arm(client, transport, owner, Arm("candidate", candidate_id), scenarios, repeat)
    return baseline, candidate, compare(baseline, candidate)


def _entries(spec: str) -> list[Any]:
    if spec == "seed":
        from aurevia.playbooks.service import SEED_FILE

        spec = str(SEED_FILE)
    data = json.loads(Path(spec).read_text(encoding="utf-8"))
    entries: list[Any] = data["entries"]
    return entries


def main(argv: list[str] | None = None) -> int:
    from aurevia.config import Settings
    from aurevia.main import create_app

    parser = argparse.ArgumentParser(prog="aurevia.evaluation.ab")
    parser.add_argument("--candidate", required=True, help="'seed' or a playbook JSON file")
    parser.add_argument("--baseline", default="none", help="'none', 'seed' or a JSON file")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", nargs="*", help="scenario names to run")
    parser.add_argument("--report", help="write a JSON report here")
    args = parser.parse_args(argv)
    scenarios = [s for s in SCENARIOS if not args.only or s.name in args.only]

    app = create_app(Settings(playbooks_enabled=True))
    transport = FakeVoiceTransport()
    app.state.voice_transport = transport  # no LiveKit rooms, nothing dialed
    with TestClient(app) as client:
        baseline, candidate, verdict = run_ab(
            client,
            transport,
            baseline_entries=None if args.baseline == "none" else _entries(args.baseline),
            candidate_entries=_entries(args.candidate),
            scenarios=scenarios,
            repeat=args.repeat,
        )
    for arm in (baseline, candidate):
        rates = arm.pass_rates()
        print(f"{arm.name}: {sum(rates.values()):.1f}/{len(rates)} scenarios (pass rate sum)")
    print("improvements: " + ("; ".join(verdict.improvements) or "none"))
    print("regressions: " + ("; ".join(verdict.regressions) or "none"))
    print("can become active: " + ("yes" if verdict.can_become_active else "no"))
    if args.report:
        report = {
            "verdict": {
                "can_become_active": verdict.can_become_active,
                "improvements": verdict.improvements,
                "regressions": verdict.regressions,
            },
            "arms": {
                arm.name: {
                    "playbook_version_id": arm.playbook_version_id,
                    "pass_rates": arm.pass_rates(),
                    "style": arm.style(),
                }
                for arm in (baseline, candidate)
            },
        }
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if verdict.can_become_active else 1


if __name__ == "__main__":
    sys.exit(main())
