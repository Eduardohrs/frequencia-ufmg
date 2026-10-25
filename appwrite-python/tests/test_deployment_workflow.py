from pathlib import Path


def test_appwrite_timeout_updates_preserve_function_access_configuration() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    assert "previous_name=$(jq -r '.name' <<< \"$previous_function\")" in workflow
    assert "mapfile -t previous_execute" in workflow
    assert "mapfile -t previous_scopes" in workflow
    assert 'test -n "$previous_name"' in workflow
    assert 'test "${#previous_execute[@]}" -gt 0' in workflow
    assert '--name "$previous_name"' in workflow
    assert 'update_args+=(--execute "$permission")' in workflow
    assert 'update_args+=(--scopes "$scope")' in workflow
    assert "update_timeout 75" in workflow
    assert 'update_timeout "$previous_timeout"' in workflow


def test_appwrite_health_checks_log_observed_status_before_rollback() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    assert "Identity health check attempt $attempt/12: HTTP $identity_status" in workflow
    assert "CORS health check attempt $attempt/6: HTTP $cors_status" in workflow
    assert "Expected HTTP 401, received HTTP $identity_status" in workflow
    assert "Expected HTTP 204, received HTTP $cors_status" in workflow
