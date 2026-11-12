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
    assert "--entrypoint src/runtime.py" in workflow
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


def test_diagnostic_database_rules_are_deployed_before_new_clients() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")
    assert workflow.index("Deploy Firestore configuration before clients") < workflow.index(
        "Publish Firebase Hosting after database rules"
    )
    assert "--only firestore:rules,firestore:indexes,hosting" not in workflow
    assert "--only firestore:rules,firestore:indexes" in workflow
    assert "--only hosting" in workflow


def test_every_flutter_action_step_pins_the_toolchain_validated_by_ci() -> None:
    workflows_dir = Path(__file__).resolve().parents[2] / ".github" / "workflows"
    workflow_names = (
        "ci.yml",
        "deploy-production.yml",
        "release.yml",
        "build-artifacts.yml",
    )
    for name in workflow_names:
        workflow = (workflows_dir / name).read_text(encoding="utf-8")
        assert "flutter-version: '3.47.9'" in workflow, name
        flutter_steps = workflow.split("- uses: subosito/flutter-action")[1:]
        assert flutter_steps, name
        for step in flutter_steps:
            block = step.split("\n      - ", maxsplit=1)[0]
            assert "flutter-version: '3.47.9'" in block, name
            assert "channel:" not in block, name


def test_deploy_provisions_appwrite_storage_before_activating_the_new_backend() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-production.yml"
    ).read_text(encoding="utf-8")

    provision_step = "Provision Appwrite storage before any function mutation (idempotent)"
    assert provision_step in workflow
    assert "python appwrite-python/setup_storage.py" in workflow
    assert "APPWRITE_ADMIN_API_KEY: ${{ secrets.APPWRITE_ADMIN_API_KEY }}" in workflow
    # Falls back to the existing deploy key when the dedicated admin secret is
    # not configured; that key must then carry the schema-write scopes.
    assert "APPWRITE_DEPLOY_KEY: ${{ secrets.APPWRITE_DEPLOY_KEY }}" in workflow
    assert 'provision_key="$APPWRITE_DEPLOY_KEY"' in workflow
    assert "tables.write" in workflow
    assert "columns.write" in workflow
    # Provisioning runs BEFORE any function mutation or deployment activation:
    # if it fails, the job stops and the previous rollout stays live.
    assert workflow.index(provision_step) < workflow.index(
        "Configure Appwrite deployment identity"
    )
    assert workflow.index(provision_step) < workflow.index(
        "Deploy Appwrite and roll back a failed activation"
    )
    assert workflow.index("Deploy Appwrite and roll back a failed activation") < workflow.index(
        "Publish Firebase Hosting after database rules"
    )
    # The runtime function key keeps its existing scopes: storage creation is
    # authorized by the admin key, not by widening required_scopes.
    scopes_block = workflow.split("required_scopes=(")[1].split(")")[0]
    for creation_scope in (
        "databases.write",
        "databases.read",
        "collections.write",
        "collections.read",
        "attributes.write",
        "attributes.read",
        "indexes.write",
        "indexes.read",
    ):
        assert creation_scope not in scopes_block
