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


def test_api_layer_does_not_issue_raw_sql() -> None:
    """Routers delegate to services; SQL text belongs in db/ and migrations."""
    offenders = [
        str(path.relative_to(SRC))
        for path in (SRC / "api").rglob("*.py")
        if "text(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
