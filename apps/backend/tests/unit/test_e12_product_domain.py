"""E12 产品化领域单元测试（T01 / T02 / T04 / T06 / T09 / T12 / T18 / T19）。"""

from __future__ import annotations

import pytest

from core.errors import ValidationFailed
from core.security.policy import evaluate
from core.security.principal import (
    ACTION_E12_PRODUCT_INSTALL,
    ACTION_E12_PRODUCT_READ,
    Principal,
)
from modules.product.compatibility import (
    FAILED,
    PASS,
    UNKNOWN,
    UNSUPPORTED,
    WARNING,
    check_component_compatibility,
    check_environment,
    matrix,
)
from modules.product.configuration import (
    assert_no_plaintext_secrets,
    is_protected_key,
    redact_configuration,
    resolve_model,
)
from modules.product.diagnostics import ERROR_CATALOG, error_entry, redact_value
from modules.product.installer import InstallationService
from modules.product.release_pipeline import REQUIRED_EVIDENCE, build_sbom
from modules.product.updates import sign_manifest, verify_signature
from modules.product.versioning import (
    COMPONENT_INDEX,
    COMPONENTS,
    CONTRACT_SUPPORTED,
    CONTRACT_UNKNOWN,
    CONTRACTS,
    compare_versions,
    component_manifest,
    contract_manifest,
    contract_status,
    declared_component_versions,
    ensure_version_isolation,
    is_newer,
    parse_version,
)

ALL_COMPONENTS = [item.component_id for item in COMPONENTS]


# --------------------------------------------------------------------- versioning
def test_parse_and_compare_versions() -> None:
    assert parse_version("1.2.3") == (1, 2, 3)
    assert compare_versions("1.0.0", "1.0.1") == -1
    assert compare_versions("2.0.0", "1.9.9") == 1
    assert is_newer("1.0.1", "1.0.0")
    with pytest.raises(ValidationFailed):
        parse_version("1.0")


def test_product_and_game_artifact_version_domains_are_isolated() -> None:
    ensure_version_isolation("product")
    with pytest.raises(ValidationFailed):
        ensure_version_isolation("game_artifact")


def test_component_manifest_declares_every_component_version() -> None:
    manifest = component_manifest()
    assert manifest["product_version"] == "1.0.0"
    assert manifest["version_domain"] == "product"
    assert manifest["game_artifact_version_domain"] == "game_artifact"
    declared = declared_component_versions()
    assert set(declared) == {item.component_id for item in COMPONENTS}
    assert declared["database_schema"] == "000033"
    assert declared["godot_plugin"] == "0.1.0"
    assert all(declared.values())


def test_contract_manifest_and_unknown_contract() -> None:
    manifest = contract_manifest()
    assert len(manifest) == len(CONTRACTS)
    assert all(item["schema_hash"] for item in manifest)
    assert contract_status("product.http_api", "1.0.0")["status"] == CONTRACT_SUPPORTED
    assert contract_status("product.http_api", "2.0.0")["status"] == CONTRACT_UNKNOWN
    assert contract_status("product.unknown", "1.0.0")["status"] == CONTRACT_UNKNOWN


# ----------------------------------------------------------------- compatibility
def test_verified_environment_passes_and_matrix_is_versioned() -> None:
    report = check_environment(
        {
            "os": "windows",
            "architecture": "x86_64",
            "godot_version": "4.5.1",
            "backend_version": "1.0.0",
            "plugin_version": "0.1.0",
            "protocol_version": "1.0.0",
            "database_schema": "000033",
            "credential_store": True,
            "disk_free_gb": 20,
            "python_version": "3.14.0",
            "network": True,
            "port_available": True,
        }
    )
    assert matrix()["matrix_version"] == "1.0.0"
    assert report.overall == PASS
    assert all(item.status == PASS for item in report.checks)


def test_unknown_environment_never_becomes_pass() -> None:
    report = check_environment({})
    assert report.overall == UNKNOWN
    assert all(item.status != PASS for item in report.checks)


def test_unsupported_platform_and_protocol_are_rejected() -> None:
    report = check_environment(
        {
            "os": "solaris",
            "architecture": "x86_64",
            "godot_version": "3.5.0",
            "protocol_version": "2.0.0",
            "database_schema": "000033",
        }
    )
    statuses = {item.key: item.status for item in report.checks}
    assert statuses["platform"] == UNSUPPORTED
    assert statuses["godot"] == UNSUPPORTED
    assert statuses["protocol"] == FAILED
    assert report.overall == FAILED


def test_schema_newer_than_product_fails_and_older_warns() -> None:
    newer = {
        item.key: item.status for item in check_component_compatibility(database_schema="000034")
    }
    older = {
        item.key: item.status for item in check_component_compatibility(database_schema="000030")
    }
    assert newer["database_schema"] == FAILED
    assert older["database_schema"] == WARNING


# --------------------------------------------------------------------- installer
def test_installation_preflight_requires_separated_directories(tmp_path) -> None:
    service = InstallationService(None)  # type: ignore[arg-type]
    install_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    ok = service.preflight(
        install_dir=str(install_dir),
        data_dir=str(data_dir),
        components=ALL_COMPONENTS,
        disk_free_gb=20,
        writable=True,
    )
    assert ok["can_install"] is True

    nested = service.preflight(
        install_dir=str(tmp_path),
        data_dir=str(tmp_path / "data"),
        components=ALL_COMPONENTS,
        disk_free_gb=20,
        writable=True,
    )
    assert nested["can_install"] is False
    assert any(item["status"] == FAILED for item in nested["checks"])


def test_installation_preflight_rejects_missing_required_components(tmp_path) -> None:
    service = InstallationService(None)  # type: ignore[arg-type]
    report = service.preflight(
        install_dir=str(tmp_path / "app"),
        data_dir=str(tmp_path / "data"),
        components=["backend"],
        disk_free_gb=20,
        writable=True,
    )
    assert report["can_install"] is False


def test_plugin_install_plan_never_overwrites_user_changes() -> None:
    service = InstallationService(None)  # type: ignore[arg-type]
    conflict = service.plugin_install_plan(
        project_dir="D:/game",
        plugin_version="0.2.0",
        existing_version="0.1.0",
        modified_files=["addons/godot_ai_agent/plugin.cfg"],
    )
    assert conflict["action"] == "CONFLICT"
    assert conflict["overwrite_user_modified"] is False
    with pytest.raises(ValidationFailed):
        service.apply_plugin_install(conflict, confirmed=True)

    applied = service.apply_plugin_install(conflict, confirmed=True, overwrite_user_modified=True)
    assert applied["applied"] is True
    assert applied["overwrote_user_modified"] is True


def test_plugin_install_plan_skip_and_unconfirmed_apply() -> None:
    service = InstallationService(None)  # type: ignore[arg-type]
    plan = service.plugin_install_plan(
        project_dir="D:/game", plugin_version="0.1.0", existing_version="0.1.0"
    )
    assert plan["action"] == "SKIP"
    assert service.apply_plugin_install(plan, confirmed=False)["applied"] is False

    fresh = service.plugin_install_plan(project_dir="D:/game", plugin_version="0.1.0")
    assert fresh["action"] == "INSTALL"
    with pytest.raises(ValidationFailed):
        service.apply_plugin_install(fresh, confirmed=False)


def test_first_run_wizard_tracks_required_context() -> None:
    service = InstallationService(None)  # type: ignore[arg-type]
    incomplete = service.first_run_wizard({})
    assert incomplete["complete"] is False
    assert incomplete["total"] == 12

    complete = service.first_run_wizard(
        {
            "backend_running": True,
            "data_dir": "D:/data",
            "credential_store": True,
            "provider_configured": True,
            "model_configured": True,
            "budget_configured": True,
            "godot_version": "4.5.1",
            "plugin_connected": True,
            "project_path": "D:/game",
        }
    )
    assert complete["complete"] is True


def test_default_paths_and_platform_data_root_are_isolated(tmp_path) -> None:
    service = InstallationService(None)  # type: ignore[arg-type]
    paths = service.default_paths(str(tmp_path))
    assert paths["config_dir"].endswith("config")
    assert paths["database_path"].endswith("data\\godot_ai_agent.db") or paths[
        "database_path"
    ].endswith("data/godot_ai_agent.db")

    windows = service.platform_data_root(
        os_name="windows", env={"LOCALAPPDATA": "C:/Users/tester/AppData/Local"}
    )
    assert windows.endswith("GodotAIAgent")

    linux = service.platform_data_root(os_name="linux", env={"XDG_DATA_HOME": "/tmp/xdg"})
    assert linux.endswith("godot-ai-agent")


# ---------------------------------------------------------------- configuration
def test_plaintext_secrets_are_rejected_and_references_allowed() -> None:
    assert_no_plaintext_secrets({"openai.api_key": "cred://openai"})
    assert_no_plaintext_secrets({"openai.api_key": "${OPENAI_API_KEY}"})
    with pytest.raises(ValidationFailed):
        assert_no_plaintext_secrets({"openai.api_key": "sk-abcdefghijklmnop"})
    with pytest.raises(ValidationFailed):
        assert_no_plaintext_secrets({"nested": {"token": "plain-value"}})


def test_protected_keys_and_safe_export() -> None:
    assert is_protected_key("security.require_signature")
    assert is_protected_key("privacy.telemetry_default")
    assert not is_protected_key("ui.theme")

    redacted = redact_configuration(
        {
            "provider": {"api_key": "sk-abcdefghijklmnop"},
            "workspace": "D:/secret/project",
            "model": "gpt-4o",
        }
    )
    assert redacted["provider"]["api_key"] == "<redacted>"
    assert redacted["workspace"] == "<path>"
    assert redacted["model"] == "gpt-4o"


def test_resolve_model_never_silently_falls_back() -> None:
    resolved = resolve_model(
        user_model="gpt-4o",
        user_provider="openai",
        available_models={"openai": ["gpt-4o"]},
    )
    assert resolved == {"provider": "openai", "model": "gpt-4o", "fallback": "none"}
    with pytest.raises(ValidationFailed):
        resolve_model(
            user_model="gpt-4o-mini",
            user_provider="openai",
            available_models={"openai": ["gpt-4o"]},
        )


# ----------------------------------------------------------------------- update
def _manifest(**overrides):
    payload = {
        "release_id": "rel-1",
        "product_version": "1.1.0",
        "channel": "STABLE",
        "component_versions": {"backend": "1.1.0"},
        "compatibility_matrix_version": "1.0.0",
        "minimum_supported_version": "1.0.0",
        "package_hash": "sha256:" + "a" * 64,
        "release_notes": "notes",
        "published_at": "2026-11-27T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_update_signature_roundtrip_and_invalid_key() -> None:
    payload = _manifest()
    key = b"product-secret"
    signature = sign_manifest(payload, key)
    assert verify_signature(payload, signature, key) == "SIGNED"
    assert verify_signature(payload, signature, b"other") == "INVALID"
    assert verify_signature(payload, None, key) == "UNSIGNED"
    assert verify_signature(payload, signature, None) == "INVALID"
    assert verify_signature(_manifest(product_version="1.2.0"), signature, key) == "INVALID"


# ------------------------------------------------------------------- diagnostics
def test_error_catalog_entries_have_recovery_and_docs() -> None:
    assert ERROR_CATALOG
    for code in ERROR_CATALOG:
        entry = error_entry(code)
        assert entry["code"] == code
        assert entry["recovery"]
        assert entry["docs"]
        assert entry["category"] != "unknown"
    fallback = error_entry("NOT_REGISTERED")
    assert fallback["category"] == "unknown"
    assert fallback["recovery"]


def test_support_bundle_redaction_removes_secrets_and_paths() -> None:
    value = {
        "api_key": "sk-abcdefghijklmnop",
        "message": "token sk-abcdefghijklmnop",
        "file": "C:/Users/tester/project/main.gd",
        "nested": [{"password": "pw"}, {"path": "D:/game"}],
        "long": "x" * 2500,
    }
    cleaned = redact_value(value)
    assert cleaned["api_key"] == "<redacted>"
    assert cleaned["message"] == "<redacted>"
    assert cleaned["file"] == "<path>"
    assert cleaned["nested"][0]["password"] == "<redacted>"
    assert cleaned["nested"][1]["path"] == "<path>"
    assert cleaned["long"].endswith("…<truncated>")


# --------------------------------------------------------------------- release
def test_release_evidence_and_sbom_are_complete() -> None:
    assert len(REQUIRED_EVIDENCE) == 7
    sbom = build_sbom()
    assert sbom["count"] == len(sbom["packages"])
    assert len(sbom["sha256"]) == 64
    assert sbom["packages"] == sorted(
        sbom["packages"], key=lambda item: (item["name"].lower(), item["version"])
    )


# ---------------------------------------------------------------------- policy
def test_product_read_is_allowed_but_changes_require_admin() -> None:
    client = Principal(client_id="cli_1", client_type="godot_editor", role="client")
    assert evaluate(client, ACTION_E12_PRODUCT_READ).allowed
    assert not evaluate(client, ACTION_E12_PRODUCT_INSTALL).allowed

    admin = Principal(client_id="cli_admin", client_type="admin", role="admin")
    assert evaluate(admin, ACTION_E12_PRODUCT_INSTALL).allowed

    agent = Principal(client_id="agent_1", client_type="agent", role="client")
    assert not evaluate(agent, ACTION_E12_PRODUCT_READ).allowed
    assert not evaluate(agent, ACTION_E12_PRODUCT_INSTALL).allowed


def test_component_index_matches_components() -> None:
    assert set(COMPONENT_INDEX) == {item.component_id for item in COMPONENTS}
