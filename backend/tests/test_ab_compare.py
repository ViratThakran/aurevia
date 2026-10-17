"""WP-12.8 rule: only an improvement with no regression can become active."""

from __future__ import annotations

from aurevia.evaluation.ab import Arm, compare
from aurevia.evaluation.scenarios import ScenarioResult

OK = "That makes sense. What do you use today?"


def _arm(name: str, passes: dict[str, list[bool]], reply: str = OK) -> Arm:
    repeats = len(next(iter(passes.values())))
    runs = [
        [ScenarioResult(n, passed=p[i], replies=[reply]) for n, p in passes.items()]
        for i in range(repeats)
    ]
    return Arm(name, None, runs)


def test_improvement_without_regression_can_become_active() -> None:
    baseline = _arm("baseline", {"asks_if_bot": [False, True], "not_interested": [True, True]})
    candidate = _arm("candidate", {"asks_if_bot": [True, True], "not_interested": [True, True]})
    verdict = compare(baseline, candidate)
    assert verdict.improvements == ["asks_if_bot: passes 50% -> 100%"]
    assert verdict.regressions == [] and verdict.can_become_active


def test_any_regression_blocks_even_with_improvements() -> None:
    baseline = _arm("baseline", {"asks_if_bot": [False], "not_interested": [True]})
    candidate = _arm("candidate", {"asks_if_bot": [True], "not_interested": [False]})
    verdict = compare(baseline, candidate)
    assert verdict.improvements and verdict.regressions == ["not_interested: passes 100% -> 0%"]
    assert not verdict.can_become_active


def test_no_change_cannot_become_active() -> None:
    same = {"asks_if_bot": [True]}
    assert not compare(_arm("a", same), _arm("b", same)).can_become_active


def test_worse_style_is_a_regression() -> None:
    stacked = "Great question! How many staff? When is renewal? Who decides?"
    verdict = compare(_arm("a", {"x": [True]}), _arm("b", {"x": [True]}, reply=stacked))
    assert any(r.startswith("multi_question_rate") for r in verdict.regressions)
    assert not verdict.can_become_active
