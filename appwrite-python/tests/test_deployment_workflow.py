from pathlib import Path


def test_appwrite_timeout_updates_preserve_the_required_function_name() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    assert "previous_name=$(jq -r '.name' <<< \"$previous_function\")" in workflow
    assert 'test -n "$previous_name"' in workflow
    assert workflow.count('--name "$previous_name"') == 2
