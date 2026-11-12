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


def test_deploy_never_provisions_schema_and_ci_has_no_key_preflight() -> None:
    workflows_dir = Path(__file__).resolve().parents[2] / ".github" / "workflows"
    deploy = (workflows_dir / "deploy-production.yml").read_text(encoding="utf-8")
    ci = (workflows_dir / "ci.yml").read_text(encoding="utf-8")

    # Schema provisioning is one-time operator work, never part of CI/deploy:
    # no admin key, no provision step, no setup_storage invocation anywhere.
    assert "APPWRITE_ADMIN_API_KEY" not in deploy
    assert "APPWRITE_ADMIN_API_KEY" not in ci
    assert "setup_storage.py" not in deploy
    assert "setup_storage.py" not in ci
    assert "Provision Appwrite storage" not in deploy
    assert "appwrite-key-preflight" not in ci
    assert "preflight_key_scopes" not in ci
    assert "workflow_dispatch" not in ci

    # The existing deployment credential is still used for the function deploy.
    assert "APPWRITE_DEPLOY_KEY: ${{ secrets.APPWRITE_DEPLOY_KEY }}" in deploy

    # Deploy ordering without the provisioning step is unchanged: configure
    # identity -> activate function deployment (with rollback) -> hosting.
    assert deploy.index("Configure Appwrite deployment identity") < deploy.index(
        "Deploy Appwrite and roll back a failed activation"
    )
    assert deploy.index("Deploy Appwrite and roll back a failed activation") < deploy.index(
        "Publish Firebase Hosting after database rules"
    )

    # The runtime function key keeps its existing scopes: no schema-write
    # scopes are required anywhere in the deploy.
    scopes_block = deploy.split("required_scopes=(")[1].split(")")[0]
    for creation_scope in (
        "databases.write",
        "databases.read",
        "collections.write",
        "collections.read",
        "attributes.write",
        "attributes.read",
        "indexes.write",
        "indexes.read",
        "tables.write",
        "columns.write",
    ):
        assert creation_scope not in scopes_block
    assert "rows.read" in scopes_block
    assert "rows.write" in scopes_block
