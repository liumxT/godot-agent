"""E12 产品化服务与 API 集成测试（T02–T12 / T19）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import ValidationFailed
from infrastructure.security.bootstrap import BootstrapTokenStore
from modules.product.configuration import ProductConfigurationService
from modules.product.diagnostics import DiagnosticsService
from modules.product.installer import InstallationService
from modules.product.licensing import LicenseService
from modules.product.migrations import ProductMigrationService
from modules.product.models import LICENSE_CLOCK_ANOMALY, LICENSE_EXPIRED, LICENSE_GRACE
from modules.product.privacy import PrivacyService
from modules.product.recovery import RecoveryService
from modules.product.release_pipeline import ProductReleaseService
from modules.product.service import ProductService
from modules.product.updates import UpdateService, sign_manifest
from modules.product.versioning import COMPONENTS

ALL_COMPONENTS = [item.component_id for item in COMPONENTS]
EVIDENCE = {
    "unit_tests": True,
    "integration_tests": True,
    "godot_plugin_tests": True,
    "compatibility_matrix": True,
    "installer_smoke": True,
    "security_scan": True,
    "rollback_drill": True,
}


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e12.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _service(app, key: str, default):
    return app.state.services.get(key, default)


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


def _install_dirs(tmp_path: Path) -> dict[str, str]:
    return {
        "install_dir": str(tmp_path / "app"),
        "data_dir": str(tmp_path / "data"),
        "config_dir": str(tmp_path / "config"),
        "log_dir": str(tmp_path / "logs"),
        "database_path": str(tmp_path / "data" / "godot.db"),
    }


# ------------------------------------------------------------------ product info
async def test_product_info_capabilities_and_health(tmp_path) -> None:
    async with _running(tmp_path) as app:
        product = _service(app, "product_service", ProductService)
        info = await product.info()
        assert info["product_version"] == "1.0.0"
        assert info["version_domain"] == "product"
        assert info["game_artifact_version_domain"] == "game_artifact"
        assert info["version_domains_isolated"] is True
        assert len(info["components"]) == len(COMPONENTS)

        capabilities = await product.capabilities()
        assert capabilities["licenses"]["status"] == "ACTIVE"
        assert capabilities["licenses"]["valid"] is True
        assert {item["key"] for item in capabilities["capabilities"]} >= {
            "development_assistant",
            "diagnostics",
        }

        health = await product.health()
        assert health["overall"] in {"WARNING", "PASS"}
        keys = {item["key"] for item in health["checks"]}
        assert keys == {"database", "schema", "installation", "license", "operations"}


async def test_installation_lifecycle_preserves_user_data(tmp_path) -> None:
    async with _running(tmp_path) as app:
        installer = _service(app, "installation_service", InstallationService)
        dirs = _install_dirs(tmp_path)

        started = await installer.start(
            **dirs, components=ALL_COMPONENTS, disk_free_gb=20, writable=True
        )
        installation_id = started["installation_id"]
        assert started["status"] == "INSTALLING"

        await installer.record_step(installation_id, step_name="copy_backend", status="COMPLETED")
        partial = await installer.verify(installation_id, {"backend_startable": True})
        assert partial["status"] == "PARTIAL"

        verification = {
            key: True
            for key in (
                "backend_startable",
                "api_reachable",
                "database_read_write",
                "migration_complete",
                "plugin_files_complete",
                "protocol_compatible",
                "websocket_connected",
                "session_lease",
                "log_dir_writable",
                "secret_store_available",
            )
        }
        completed = await installer.verify(installation_id, verification)
        assert completed["status"] == "COMPLETED"
        assert (await installer.get(installation_id))["status"] == "COMPLETED"

        health = await _service(app, "product_service", ProductService).health()
        assert health["overall"] == "PASS"

        rolled = await installer.rollback(installation_id)
        assert rolled["status"] == "ROLLED_BACK"
        assert str(tmp_path / "data") in rolled["preserved"]

        uninstall = await installer.uninstall(installation_id)
        assert uninstall["project_files_touched"] is False
        assert uninstall["requires_confirmation"] is True


async def test_installation_verify_failure_requires_recovery(tmp_path) -> None:
    async with _running(tmp_path) as app:
        installer = _service(app, "installation_service", InstallationService)
        started = await installer.start(
            **_install_dirs(tmp_path),
            components=ALL_COMPONENTS,
            disk_free_gb=20,
            writable=True,
        )
        result = await installer.verify(started["installation_id"], {"backend_startable": False})
        assert result["status"] == "RECOVERY_REQUIRED"


# ----------------------------------------------------------------- configuration
async def test_configuration_layers_and_protected_keys(tmp_path) -> None:
    async with _running(tmp_path) as app:
        config = _service(app, "configuration_service", ProductConfigurationService)
        await config.upsert_profile(
            profile_name="system",
            scope="SYSTEM_DEFAULT",
            values={"ui.theme": "dark", "security.require_signature": True},
        )
        await config.upsert_profile(
            profile_name="user",
            scope="USER_GLOBAL",
            values={"ui.theme": "light", "security.require_signature": False},
        )
        effective = await config.resolve_effective()
        assert effective["values"]["ui.theme"] == "light"
        assert effective["values"]["security.require_signature"] is True
        assert "security.require_signature" in effective["ignored_protected"]

        with pytest.raises(ValidationFailed):
            await config.upsert_profile(
                profile_name="bad",
                scope="USER_GLOBAL",
                values={"openai.api_key": "sk-abcdefghijklmnop"},
            )

        exported = await config.export_safe()
        assert exported["contains_project_source"] is False


# --------------------------------------------------------------------- license
async def test_license_grace_expiry_and_feature_revocation(tmp_path) -> None:
    async with _running(tmp_path) as app:
        licenses = _service(app, "license_service", LicenseService)
        issued = datetime.now(UTC) - timedelta(days=30)
        expires = datetime.now(UTC) - timedelta(days=2)
        registered = await licenses.register(
            license_mode="ONLINE",
            license_reference="lic-ref",
            issued_at=issued,
            expires_at=expires,
            offline_grace_days=7,
            features=("multi_agent",),
        )
        grace = await licenses.evaluate()
        assert grace["status"] == LICENSE_GRACE
        assert grace["valid"] is True

        expired = await licenses.evaluate(now=datetime.now(UTC) + timedelta(days=30))
        assert expired["status"] == LICENSE_EXPIRED
        assert expired["valid"] is False

        clock = await licenses.evaluate(now=issued - timedelta(days=5))
        assert clock["status"] == LICENSE_CLOCK_ANOMALY
        assert clock["valid"] is False

        assert await licenses.has_feature("multi_agent") is True
        await licenses.revoke(registered["license_id"], "multi_agent")
        assert await licenses.has_feature("multi_agent") is False
        assert await licenses.has_feature("unknown_feature") is False


# ---------------------------------------------------------------------- update
async def test_update_requires_signature_and_approval(tmp_path) -> None:
    async with _running(tmp_path) as app:
        updates = _service(app, "update_service", UpdateService)
        key = b"update-key"

        unsigned = await updates.register_manifest(_manifest())
        assert unsigned["signature_status"] == "UNSIGNED"
        with pytest.raises(ValidationFailed):
            await updates.create_operation(unsigned["manifest_id"])

        payload = _manifest()
        signed = await updates.register_manifest(
            payload, signature=sign_manifest(payload, key), signing_key=key
        )
        assert signed["signature_status"] == "SIGNED"

        operation = await updates.create_operation(signed["manifest_id"])
        assert operation["approved"] is False
        with pytest.raises(ValidationFailed):
            await updates.install(operation["operation_id"])

        approved = await updates.approve(operation["operation_id"])
        assert approved["status"] == "APPROVED"
        installed = await updates.install(operation["operation_id"])
        assert installed["status"] == "COMPLETED"

        downgrade = _manifest(product_version="0.9.0")
        downgrade_manifest = await updates.register_manifest(
            downgrade, signature=sign_manifest(downgrade, key), signing_key=key
        )
        with pytest.raises(ValidationFailed):
            await updates.create_operation(downgrade_manifest["manifest_id"])


async def test_update_manifest_validation_and_channel_check(tmp_path) -> None:
    async with _running(tmp_path) as app:
        updates = _service(app, "update_service", UpdateService)
        with pytest.raises(ValidationFailed):
            await updates.register_manifest(_manifest(package_hash="not-a-hash"))
        with pytest.raises(ValidationFailed):
            await updates.register_manifest(_manifest(channel="NIGHTLY"))
        with pytest.raises(ValidationFailed):
            await updates.register_manifest(_manifest(release_notes=""))

        await updates.record_release(
            {
                "release_id": "rel-110",
                "product_version": "1.1.0",
                "channel": "STABLE",
                "status": "APPROVED",
            }
        )
        check = await updates.check("STABLE")
        assert check["update_available"] is True
        assert check["latest_version"] == "1.1.0"
        assert (await updates.check("BETA"))["update_available"] is False


# ------------------------------------------------------------------- migration
async def test_migration_requires_confirmation_backup_and_completes(tmp_path) -> None:
    async with _running(tmp_path) as app:
        migrations = _service(app, "product_migration_service", ProductMigrationService)
        plan = await migrations.plan(current_schema_version="000030")
        assert plan["status"] == "MIGRATION_REQUIRED"
        assert plan["backup_requirement"] is True

        run = await migrations.prepare(plan["migration_id"])
        with pytest.raises(ValidationFailed):
            await migrations.execute(run["run_id"], confirmed=False)

        result = await migrations.execute(run["run_id"], confirmed=True)
        assert result["status"] == "COMPLETED"
        assert result["backup_path"]
        status = await migrations.status()
        assert status["unfinished_runs"] == []


async def test_migration_downgrade_and_already_at_target(tmp_path) -> None:
    async with _running(tmp_path) as app:
        migrations = _service(app, "product_migration_service", ProductMigrationService)
        assert (await migrations.plan(current_schema_version="000034"))["status"] == (
            "DOWNGRADE_BLOCKED"
        )
        assert (await migrations.plan(current_schema_version="000033"))["status"] == (
            "ALREADY_AT_TARGET"
        )
        with pytest.raises(ValidationFailed):
            await migrations.plan(current_schema_version="schema-x")


# -------------------------------------------------------------------- recovery
async def test_recovery_unknown_state_requires_manual_verification(tmp_path) -> None:
    async with _running(tmp_path) as app:
        recovery = _service(app, "recovery_service", RecoveryService)
        point = await recovery.create_point(
            kind="PLUGIN",
            path=str(tmp_path / "plugin-backup.zip"),
            integrity_hash="sha256:" + "b" * 64,
            description="plugin",
            product_version="1.0.0",
        )
        inspection = await recovery.inspect(point["recovery_point_id"])
        assert inspection["external"]["tasks"]["status"] == "UNKNOWN"

        plan = await recovery.plan(inspection["operation_id"])
        assert plan["plan"]["requires_manual_verification"] is True
        assert plan["plan"]["delete_user_project"] is False
        assert plan["plan"]["preserve_user_data"] is True

        with pytest.raises(ValidationFailed):
            await recovery.execute(inspection["operation_id"], confirmed=True)

        executed = await recovery.execute(
            inspection["operation_id"],
            confirmed=True,
            manual_verification_done=True,
        )
        assert executed["status"] == "RECOVERED"
        assert executed["preserved_user_data"] is True
        assert executed["deleted_user_project"] is False
        assert (await recovery.list_points())[0]["recovery_point_id"] == (
            point["recovery_point_id"]
        )


# ----------------------------------------------------------------- diagnostics
async def test_support_bundle_redacts_secrets_and_requires_confirmation(tmp_path) -> None:
    async with _running(tmp_path) as app:
        diagnostics = _service(app, "diagnostics_service", DiagnosticsService)
        context = {
            "product": {"version": "1.0.0"},
            "environment": {"workspace": "C:/Users/tester/game"},
            "logs": ["token sk-abcdefghijklmnop"],
        }
        preview = diagnostics.prepare_bundle(context, logs=["password=pw"])
        assert preview["contains_project_source"] is False
        assert preview["contains_secrets"] is False
        assert preview["bundle"]["excluded"]["project_source"] is True

        with pytest.raises(ValidationFailed):
            await diagnostics.export_bundle(context, created_by="cli_admin")

        exported = await diagnostics.export_bundle(
            context, created_by="cli_admin", confirmed=True, logs=["sk-abcdefghijklmnop"]
        )
        bundle_path = Path(exported["path"])
        assert bundle_path.exists()
        serialized = bundle_path.read_text(encoding="utf-8")
        assert "sk-abcdefghijklmnop" not in serialized
        assert "C:/Users/tester" not in serialized
        assert exported["sha256"] == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        assert (await diagnostics.list_bundles())[0]["bundle_id"] == exported["bundle_id"]

        crash = await diagnostics.report_crash(
            error_code="PROTOCOL_INCOMPATIBLE",
            summary="token sk-abcdefghijklmnop",
            context={"api_key": "sk-abcdefghijklmnop"},
        )
        assert crash["status"] == "LOCAL_ONLY"
        assert crash["sent"] is False


# --------------------------------------------------------------------- privacy
async def test_privacy_telemetry_defaults_off_and_deletion_scope(tmp_path) -> None:
    async with _running(tmp_path) as app:
        privacy = _service(app, "privacy_service", PrivacyService)
        state = await privacy.telemetry_state()
        assert state["enabled"] is False
        assert state["default"] == "OFF"

        with pytest.raises(ValidationFailed):
            await privacy.set_telemetry(enabled=True, categories=[], actor="cli_admin")
        enabled = await privacy.set_telemetry(enabled=True, categories=["crash"], actor="cli_admin")
        assert enabled["enabled"] is True
        assert enabled["categories"] == ["crash"]

        preview = await privacy.context_preview(
            {"prompt": "build", "api_key": "sk-abcdefghijklmnop", "project": "D:/game"}
        )
        assert preview["secrets_included"] is False
        assert preview["project_source_included"] is False
        assert preview["sent_to_model"]["api_key"] == "<redacted>"

        with pytest.raises(ValidationFailed):
            await privacy.delete_user_data(scope="project", confirmed=True)
        with pytest.raises(ValidationFailed):
            await privacy.delete_user_data(scope="telemetry", confirmed=False)

        deleted = await privacy.delete_user_data(scope="telemetry", confirmed=True)
        assert deleted["project_files_touched"] is False
        assert (await privacy.telemetry_state())["enabled"] is False


# --------------------------------------------------------------------- release
async def test_product_release_requires_evidence_signature_and_approval(tmp_path) -> None:
    async with _running(tmp_path) as app:
        releases = _service(app, "product_release_service", ProductReleaseService)
        with pytest.raises(ValidationFailed):
            await releases.create_candidate(
                product_version="1.1.0",
                channel="STABLE",
                component_versions={"backend": "1.1.0"},
                package_hash="sha256:" + "c" * 64,
                signature_status="SIGNED",
                release_notes="",
                evidence={"unit_tests": True},
            )

        unsigned = await releases.create_candidate(
            product_version="1.1.0",
            channel="STABLE",
            component_versions={"backend": "1.1.0"},
            package_hash="sha256:" + "c" * 64,
            signature_status="UNSIGNED",
            release_notes="",
            evidence=EVIDENCE,
        )
        with pytest.raises(ValidationFailed):
            await releases.approve(unsigned["release_id"], approver="admin")

        candidate = await releases.create_candidate(
            product_version="1.2.0",
            channel="STABLE",
            component_versions={"backend": "1.2.0"},
            package_hash="sha256:" + "d" * 64,
            signature_status="SIGNED",
            release_notes="",
            evidence=EVIDENCE,
        )
        with pytest.raises(ValidationFailed):
            await releases.publish(candidate["release_id"], publisher="admin")

        approved = await releases.approve(candidate["release_id"], approver="admin")
        assert approved["status"] == "APPROVED"
        published = await releases.publish(candidate["release_id"], publisher="admin")
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None
        assert len(await releases.list_releases("STABLE")) == 2

        with pytest.raises(ValidationFailed):
            await releases.create_candidate(
                product_version="1.1.0",
                channel="STABLE",
                component_versions={"backend": "1.1.0"},
                package_hash="sha256:" + "e" * 64,
                signature_status="SIGNED",
                release_notes="",
                evidence=EVIDENCE,
                version_domain="game_artifact",
            )


# ------------------------------------------------------------------------- API
def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _credentials(app, client, *, client_type: str) -> dict[str, str]:
    bootstrap = app.state.services.get("bootstrap_token", BootstrapTokenStore).token
    registered = await client.post(
        "/api/v1/clients",
        json={"client_type": client_type, "client_name": f"Client {client_type}"},
        headers={"X-Bootstrap-Token": bootstrap},
    )
    body = registered.json()
    challenge = (
        await client.post("/api/v1/auth/challenge", json={"client_id": body["client_id"]})
    ).json()
    digest = hmac.new(
        body["client_secret"].encode(),
        f"{challenge['challenge_id']}.{challenge['challenge']}".encode(),
        hashlib.sha256,
    ).digest()
    verified = await client.post(
        "/api/v1/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "client_id": body["client_id"],
            "proof": base64.urlsafe_b64encode(digest).decode().rstrip("="),
        },
    )
    return {"client_id": body["client_id"], "access_token": verified.json()["access_token"]}


async def test_product_api_permissions_and_metadata(tmp_path) -> None:
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e12api.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unauthenticated = await client.get("/api/v1/product/info")
            assert unauthenticated.status_code == 401

            editor = await _credentials(app, client, client_type="godot_editor")
            admin = await _credentials(app, client, client_type="admin")

            info = await client.get("/api/v1/product/info", headers=_bearer(editor["access_token"]))
            assert info.status_code == 200
            assert info.json()["product_version"] == "1.0.0"

            health = await client.get(
                "/api/v1/product/health", headers=_bearer(editor["access_token"])
            )
            assert health.status_code == 200
            assert health.json()["overall"] in {"PASS", "WARNING"}

            denied = await client.post(
                "/api/v1/product/installations/preflight",
                json={
                    "install_dir": str(tmp_path / "app"),
                    "data_dir": str(tmp_path / "data"),
                    "components": ALL_COMPONENTS,
                    "disk_free_gb": 20,
                    "writable": True,
                },
                headers=_bearer(editor["access_token"]),
            )
            assert denied.status_code == 403

            allowed = await client.post(
                "/api/v1/product/installations/preflight",
                json={
                    "install_dir": str(tmp_path / "app"),
                    "data_dir": str(tmp_path / "data"),
                    "components": ALL_COMPONENTS,
                    "disk_free_gb": 20,
                    "writable": True,
                },
                headers=_bearer(admin["access_token"]),
            )
            assert allowed.status_code == 200
            assert allowed.json()["can_install"] is True

            sbom = await client.get("/api/v1/product/sbom", headers=_bearer(editor["access_token"]))
            assert sbom.status_code == 200
            assert sbom.json()["count"] == len(sbom.json()["packages"])

            release = await client.post(
                "/api/v1/product/releases",
                json={
                    "product_version": "1.1.0",
                    "channel": "STABLE",
                    "component_versions": {"backend": "1.1.0"},
                    "package_hash": "sha256:" + "f" * 64,
                    "signature_status": "SIGNED",
                    "release_notes": "",
                    "evidence": EVIDENCE,
                },
                headers=_bearer(editor["access_token"]),
            )
            assert release.status_code == 403
