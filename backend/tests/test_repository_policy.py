"""Tests for repository-level security and supply-chain contracts."""

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_firebase_hosting_declares_baseline_security_headers() -> None:
    """The deployed web client keeps its browser hardening contract."""

    firebase_config = json.loads(
        (REPOSITORY_ROOT / "firebase.json").read_text(encoding="utf-8")
    )
    headers = {
        header["key"]: header["value"]
        for rule in firebase_config["hosting"]["headers"]
        for header in rule["headers"]
    }

    assert headers["Strict-Transport-Security"].startswith("max-age=")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"


def test_github_actions_are_pinned_to_immutable_commits() -> None:
    """Third-party workflow code cannot change behind a mutable version tag."""

    workflows = REPOSITORY_ROOT / ".github" / "workflows"
    uses_pattern = re.compile(r"^\s*-\s+uses:\s+[^@\s]+@([^#\s]+)")
    references = [
        match.group(1)
        for workflow in workflows.glob("*.yml")
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if (match := uses_pattern.match(line))
    ]

    assert references
    assert all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references)
