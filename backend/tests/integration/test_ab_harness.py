"""WP-12.8 A/B harness end to end with the fake model: both arms, the playbook only in one."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aurevia.evaluation.ab import run_ab
from aurevia.evaluation.scenarios import SCENARIOS
from aurevia.gateway import ModelGateway
from aurevia.main import create_app
from aurevia.playbooks.service import seed_entries
from aurevia.providers.fakes import FakeModelProvider, FakeVoiceTransport
from tests.conftest import TEST_JWT_SECRET, SettingsFactory
from tests.integration.conftest import PgEnv, admin_fetch

BOT = next(s for s in SCENARIOS if s.name == "asks_if_bot")  # two prospect lines


def test_ab_runs_both_arms_and_applies_the_rule(db: PgEnv, make_settings: SettingsFactory) -> None:
    settings = make_settings(
        database_url=db.app_url,
        jwt_secret=TEST_JWT_SECRET,
        database_app_role=db.app_role,
        playbooks_enabled=True,
    )
    app = create_app(settings)
    transport = FakeVoiceTransport()
    # Scripted: the baseline arm breaks the honesty rule, the candidate arm does not.
    model = FakeModelProvider(
        replies=[
            "Hi, it's Aria from Sunrise.",
            "Yes, I'm a real person.",
            "Hi, it's Aria from Sunrise.",
            "I'm an AI assistant for Sunrise. Is now an okay time?",
        ]
    )
    app.state.voice_transport = transport
    app.state.model_gateway = ModelGateway(
        model,
        model="test-model",
        max_tokens=256,
        first_token_timeout_seconds=5,
        total_timeout_seconds=10,
    )
    entries = [e.model_dump(mode="json") for e in seed_entries()]
    with TestClient(app) as client:
        baseline, candidate, verdict = run_ab(
            client, transport, baseline_entries=None, candidate_entries=entries, scenarios=[BOT]
        )

    assert baseline.pass_rates() == {"asks_if_bot": 0.0}
    assert candidate.pass_rates() == {"asks_if_bot": 1.0}
    assert verdict.can_become_active and verdict.regressions == []
    # The playbook reached the model only in the candidate arm.
    prompts = [r.system for r in model.requests]
    assert ["Ideas from expert callers" in p for p in prompts] == [False, False, True, True]
    # Every offer is stored with the version that made it (the "version per call" record).
    offers = admin_fetch(db, "SELECT DISTINCT version_id FROM playbook_offers")
    assert [str(r["version_id"]) for r in offers] == [candidate.playbook_version_id]
    assert baseline.playbook_version_id is None
