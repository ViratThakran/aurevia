"""Architecture rules from docs/AGENTS.md, enforced on every test run."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "aurevia"

# Vendor SDKs that may only ever be imported under aurevia/providers/.
VENDOR_SDKS = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "deepgram",
        "assemblyai",
        "elevenlabs",
        "cartesia",
        "sarvamai",
        "livekit",
        "pipecat",
        "twilio",
        "exotel",
        "plivo",
    }
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_vendor_sdks_are_imported_only_by_providers() -> None:
    offenders = {
        str(path.relative_to(SRC)): sorted(_imports(path) & VENDOR_SDKS)
        for path in SRC.rglob("*.py")
        if "providers" not in path.relative_to(SRC).parts and _imports(path) & VENDOR_SDKS
    }
    assert offenders == {}


def _imports_raw_sql(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "sqlalchemy"
            and any(alias.name == "text" for alias in node.names)
        ):
            return True
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "text"
            and isinstance(node.value, ast.Name)
            and node.value.id in {"sqlalchemy", "sa"}
        ):
            return True
    return False


def test_api_layer_does_not_issue_raw_sql() -> None:
    """Routers delegate to services; raw SQL (``sqlalchemy.text``) belongs in db/ and
    migrations."""
    offenders = [
        str(path.relative_to(SRC)) for path in (SRC / "api").rglob("*.py") if _imports_raw_sql(path)
    ]
    assert offenders == []


def test_raw_sql_detector_catches_text_imports(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("from sqlalchemy import select, text\n", encoding="utf-8")
    assert _imports_raw_sql(sample)
    sample.write_text("ctx = PromptContext(set_tenant_context(x))\n", encoding="utf-8")
    assert not _imports_raw_sql(sample)


def _calls_and_names(path: Path) -> tuple[set[str], set[str]]:
    """Attribute/function names called, and every bare name used, in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return called, names


def _modules_outside_providers() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "providers" not in p.relative_to(SRC).parts]


def test_only_the_gated_dialer_places_calls() -> None:
    """Phase 6 gate: ``place_call`` is reached from exactly one function, which needs an
    Approval."""
    callers = sorted(
        str(p.relative_to(SRC)).replace("\\", "/")
        for p in _modules_outside_providers()
        if "place_call" in _calls_and_names(p)[0]
    )
    assert callers == ["telephony/service.py"]


def test_only_the_gate_issues_approvals() -> None:
    issuers = sorted(
        str(p.relative_to(SRC)).replace("\\", "/")
        for p in SRC.rglob("*.py")
        if "Approval" in _calls_and_names(p)[0] or "_GATE_KEY" in _calls_and_names(p)[1]
    )
    assert issuers == ["compliance/gate.py"]


def test_an_approval_cannot_be_forged() -> None:
    import uuid
    from datetime import UTC, datetime

    import pytest

    from aurevia.compliance.gate import Approval
    from aurevia.compliance.policy import CallPurpose

    with pytest.raises(PermissionError):
        Approval(
            decision_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            lead_id=uuid.uuid4(),
            to_number="+919876543210",
            from_number="+911401234567",
            purpose=CallPurpose.PROMOTIONAL,
            issued_at=datetime.now(UTC),
        )
