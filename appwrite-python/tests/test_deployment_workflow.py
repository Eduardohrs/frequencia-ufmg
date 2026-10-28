from pathlib import Path


def test_appwrite_timeout_updates_restore_required_access_configuration() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    assert "previous_name=$(jq -r '.name' <<< \"$previous_function\")" in workflow
    assert "required_execute=(any)" in workflow
    assert "required_scopes=(" in workflow
    assert "rows.read" in workflow
    assert "rows.write" in workflow
    assert "documentsdb.documents.read" in workflow
    assert "documentsdb.documents.write" in workflow
    assert "vectorsdb.documents.read" in workflow
    assert "vectorsdb.documents.write" in workflow
    assert 'test -n "$previous_name"' in workflow
    assert '--name "$previous_name"' in workflow
    assert 'update_args+=(--execute "$permission")' in workflow
    assert 'update_args+=(--scopes "$scope")' in workflow
    assert "configure_function 900" in workflow
    assert 'configure_function "$previous_timeout"' in workflow
    assert workflow.index("configure_function 900") < workflow.index(
        "functions create-deployment"
    )
    assert workflow.index("functions create-deployment") < workflow.index(
        "functions update-function-deployment"
    )
    assert 'test "$(jq -r \'.live\' <<< "$active_function")" = "true"' in workflow
    assert "The previous deployment was already stale" in workflow


def test_appwrite_health_checks_log_observed_status_before_rollback() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    assert "Identity health check attempt $attempt/12: HTTP $identity_status" in workflow
    assert "CORS health check attempt $attempt/6: HTTP $cors_status" in workflow
    assert "Expected HTTP 401, received HTTP $identity_status" in workflow
    assert "Expected HTTP 204, received HTTP $cors_status" in workflow
