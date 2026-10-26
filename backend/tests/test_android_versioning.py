import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _version(tmp_path: Path, timestamp: int) -> subprocess.CompletedProcess[str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": f"{timestamp} +0000",
        "GIT_COMMITTER_DATE": f"{timestamp} +0000",
        "GITHUB_ENV": str(tmp_path / "env"),
    }
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        env=env,
        check=True,
    )
    action = (ROOT / ".github/actions/android-version/action.yml").read_text()
    script = textwrap.dedent(action.split("run: |\n", 1)[1])
    git = Path(shutil.which("git") or "git")
    bash = str(git.parent.parent / "bin/bash.exe") if os.name == "nt" else "bash"
    return subprocess.run(
        [bash, "-c", script], cwd=tmp_path, env=env, text=True, capture_output=True, check=False
    )


def test_newer_revision_is_newer_than_both_legacy_workflow_counters(tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    assert _version(first, 1793000000).returncode == 0
    assert _version(second, 1793000001).returncode == 0
    old = int((first / "env").read_text().strip().split("=")[1])
    new = int((second / "env").read_text().strip().split("=")[1])
    assert 36 < old < new <= 2100000000


@pytest.mark.parametrize("timestamp", [1704067200, 4000000000])
def test_refuses_versions_outside_android_range(tmp_path: Path, timestamp: int) -> None:
    assert _version(tmp_path, timestamp).returncode == 1
    assert not (tmp_path / "env").exists()


def test_every_apk_builder_uses_the_shared_version_action() -> None:
    for name in ("build-artifacts.yml", "deploy-production.yml", "release.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text()
        assert "uses: ./.github/actions/android-version" in workflow
        assert '--build-number "$GITHUB_RUN_NUMBER"' not in workflow
        assert '--build-number="$GITHUB_RUN_NUMBER"' not in workflow
        assert '"$ANDROID_VERSION_CODE"' in workflow
