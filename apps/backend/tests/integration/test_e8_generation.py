"""E8-M3 资产生成编排集成测试。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from bootstrap.application import create_app
from config.settings import load_settings
from core.errors import (
    AssetBriefInvalid,
    AssetGenerationInvalid,
    AssetGenerationUnknown,
    ModelCallFailed,
    ModelUnavailable,
)
from infrastructure.database.service import DatabaseService
from modules.asset_pipeline.briefs import AssetBriefService
from modules.asset_pipeline.generation import GenerationOrchestrator, GenerationRequest
from modules.asset_pipeline.models import STORAGE_GENERATED
from modules.asset_pipeline.repository import (
    AssetProvenanceRepository,
    AssetStorageObjectRepository,
)
from modules.asset_pipeline.service import AssetService
from modules.asset_pipeline.versioning import AssetVersionService
from modules.model_gateway.asset_generation import (
    ASSET_JOB_RUNNING,
    ASSET_JOB_SUCCEEDED,
    ASSET_KIND_IMAGE,
    AssetAdapterCapabilities,
    AssetAdapterRegistry,
    AssetGenerationOutput,
    AssetGenerationRequest,
    AssetGenerationResult,
    BaseAssetGenerationAdapter,
)
from modules.model_gateway.configuration import ProviderConfigurationService
from modules.model_gateway.gateway import ModelGatewayService
from modules.model_gateway.models import (
    CAPABILITY_IMAGE_OUTPUT,
    CAPABILITY_SUPPORTED,
    CAPABILITY_TEXT_INPUT,
    CAPABILITY_UNKNOWN,
    MODEL_DISABLED,
    PROVIDER_TYPE_LOCAL,
)
from modules.model_gateway.providers.base import ProviderCallFailure
from modules.model_gateway.providers.errors import ProviderErrorCategory, ProviderErrorInfo
from modules.model_gateway.registry import CapabilitySetting, ModelRegistryService
from modules.project_registry.service import ProjectRegistryService


class FakeState:
    def __init__(self, mode: str = "sync") -> None:
        self.mode = mode
        self.submits = 0
        self.queries = 0
        self.cancels = 0
        self.prompts: list[str] = []


class FakeImageAdapter(BaseAssetGenerationAdapter):
    kind = ASSET_KIND_IMAGE
    provider_types = frozenset({PROVIDER_TYPE_LOCAL})
    formats = frozenset({"png"})
    max_output_count = 4
    requires_api_key = False
    allowed_schemes = frozenset({"http", "https"})
    default_format = "png"

    def __init__(self, *, state: FakeState, **kwargs) -> None:
        super().__init__(**kwargs)
        self.state = state

    def validate_configuration(self) -> None:
        return None

    def get_capabilities(self) -> AssetAdapterCapabilities:
        return AssetAdapterCapabilities(
            kind=self.kind,
            formats=self.formats,
            max_output_count=self.max_output_count,
            supports_async=self.state.mode == "async",
            supports_cancel=self.state.mode == "async",
        )

    async def submit_generation(
        self, request: AssetGenerationRequest
    ) -> AssetGenerationResult:
        self.state.submits += 1
        self.state.prompts.append(request.prompt)
        if self.state.mode == "unknown":
            raise ProviderCallFailure(
                ProviderErrorInfo(
                    category=ProviderErrorCategory.UNKNOWN_RESULT,
                    message="provider timeout after send",
                    retryable=False,
                ),
                sent=True,
            )
        if self.state.mode == "failed":
            raise ProviderCallFailure(
                ProviderErrorInfo(
                    category=ProviderErrorCategory.INVALID_REQUEST,
                    message="invalid prompt",
                    retryable=False,
                ),
                sent=True,
            )
        if self.state.mode == "async":
            return AssetGenerationResult(
                status=ASSET_JOB_RUNNING, provider_job_id="job-async-1"
            )
        return AssetGenerationResult(
            status=ASSET_JOB_SUCCEEDED,
            provider_job_id="job-sync-1",
            outputs=self._outputs(request),
        )

    async def query_generation(
        self, request: AssetGenerationRequest, provider_job_id: str
    ) -> AssetGenerationResult:
        self.state.queries += 1
        return AssetGenerationResult(
            status=ASSET_JOB_SUCCEEDED,
            provider_job_id=provider_job_id,
            outputs=self._outputs(request),
        )

    async def cancel_generation(
        self, request: AssetGenerationRequest, provider_job_id: str
    ) -> AssetGenerationResult:
        self.state.cancels += 1
        return AssetGenerationResult(
            status=ASSET_JOB_RUNNING, provider_job_id=provider_job_id
        )

    def _outputs(
        self, request: AssetGenerationRequest
    ) -> tuple[AssetGenerationOutput, ...]:
        return (
            AssetGenerationOutput(
                data=f"generated:{request.prompt}".encode(),
                format="png",
                width=request.parameter("width"),
                height=request.parameter("height"),
            ),
        )


@asynccontextmanager
async def _running(tmp_path: Path):
    settings = load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'e8gen.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings)
    async with app.state.lifecycle.lifespan(app):
        yield app


def _database(app) -> DatabaseService:
    return app.state.services.get("database", DatabaseService)


def _registry(app) -> ModelRegistryService:
    return app.state.services.get("model_registry_service", ModelRegistryService)


def _orchestrator(app, state: FakeState) -> GenerationOrchestrator:
    adapters = AssetAdapterRegistry()
    adapters.register(
        ASSET_KIND_IMAGE,
        PROVIDER_TYPE_LOCAL,
        lambda **kwargs: FakeImageAdapter(state=state, **kwargs),
    )
    gateway = ModelGatewayService(
        _database(app),
        app.state.services.get("secret_store"),
        _registry(app),
        asset_adapters=adapters,
        default_timeout_seconds=5,
    )
    return GenerationOrchestrator(
        _database(app),
        gateway=gateway,
        storage=app.state.services.get("asset_storage"),
        versions=app.state.services.get("asset_version_service", AssetVersionService),
        briefs=app.state.services.get("asset_brief_service", AssetBriefService),
    )


async def _seed(app, tmp_path: Path, *, capability: str = CAPABILITY_IMAGE_OUTPUT):
    root = tmp_path / "game"
    root.mkdir(exist_ok=True)
    (root / "project.godot").write_text("[application]\n", encoding="utf-8")
    projects = app.state.services.get("project_registry_service", ProjectRegistryService)
    project = await projects.register(project_root=str(root), name="E8 Generation")
    assets = app.state.services.get("asset_service", AssetService)
    asset = await assets.create(
        project_id=project.project_id,
        name="hero",
        category="IMAGE",
        asset_type="CHARACTER",
    )
    briefs = app.state.services.get("asset_brief_service", AssetBriefService)
    brief = await briefs.create(
        project_id=project.project_id,
        title="Hero idle",
        asset_category="IMAGE",
        asset_id=asset.asset_id,
        technical_constraints={"width": 512, "height": 512, "format": "png"},
    )
    await briefs.propose(brief.brief_id)
    await briefs.approve(brief.brief_id)
    registry = _registry(app)
    provider = await registry.register_provider(
        name="local-assets", provider_type=PROVIDER_TYPE_LOCAL
    )
    configuration = app.state.services.get(
        "provider_configuration_service", ProviderConfigurationService
    )
    await configuration.save(
        provider.provider_id, endpoint="http://127.0.0.1:9000", timeout_seconds=5
    )
    supported = CapabilitySetting(
        support_status=CAPABILITY_SUPPORTED, evidence_source="test"
    )
    status = CAPABILITY_SUPPORTED if capability == CAPABILITY_IMAGE_OUTPUT else CAPABILITY_UNKNOWN
    model = await registry.register_model(
        provider_id=provider.provider_id,
        model_key="fake-image-model",
        display_name="Fake Image",
        context_window=4096,
        max_output_tokens=1024,
        capabilities={
            CAPABILITY_IMAGE_OUTPUT: CapabilitySetting(
                support_status=status, evidence_source="test"
            ),
            CAPABILITY_TEXT_INPUT: supported,
        },
        input_price="0",
        output_price="0",
        source="test",
    )
    return project, asset, brief, provider, model


def _request(
    project_id: str,
    asset_id: str,
    brief_id: str,
    provider_id: str,
    model_id: str,
    **overrides,
) -> GenerationRequest:
    payload = {
        "project_id": project_id,
        "asset_id": asset_id,
        "kind": ASSET_KIND_IMAGE,
        "prompt": "pixel art hero",
        "provider_id": provider_id,
        "model_id": model_id,
        "brief_id": brief_id,
        "parameters": {"width": 512, "height": 512, "format": "png"},
    }
    payload.update(overrides)
    return GenerationRequest(**payload)


@pytest.mark.asyncio
async def test_generation_success_creates_version_provenance_and_storage(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        state = FakeState()
        project, asset, brief, provider, model = await _seed(app, tmp_path)
        orchestrator = _orchestrator(app, state)
        assets = app.state.services.get("asset_service", AssetService)
        storage = app.state.services.get("asset_storage")

        view = await orchestrator.submit(
            _request(
                project.project_id,
                asset.asset_id,
                brief.brief_id,
                provider.provider_id,
                model.model_id,
            )
        )

        assert view.status == "SUCCEEDED"
        assert state.submits == 1
        assert view.result_version_id is not None
        assert len(view.outputs) == 1
        current = await assets.get(asset.asset_id)
        assert current.current_version_id == view.result_version_id
        reference = view.outputs[0].reference
        assert storage.read_bytes(project.project_id, STORAGE_GENERATED, reference) == (
            b"generated:pixel art hero"
        )
        async with _database(app).session() as session:
            provenance = await AssetProvenanceRepository(session).get_for_version(
                view.result_version_id
            )
            objects = await AssetStorageObjectRepository(session).list_for_version(
                view.result_version_id
            )
        assert provenance is not None
        assert provenance.source_type == "AI_GENERATED"
        assert provenance.provider_id == provider.provider_id
        assert provenance.model_id == model.model_id
        assert len(objects) == 1
        assert objects[0].relative_path == reference


@pytest.mark.asyncio
async def test_generation_idempotency_prevents_duplicate_provider_calls(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        state = FakeState()
        project, asset, brief, provider, model = await _seed(app, tmp_path)
        orchestrator = _orchestrator(app, state)
        request = _request(
            project.project_id,
            asset.asset_id,
            brief.brief_id,
            provider.provider_id,
            model.model_id,
            idempotency_key="hero-idle-1",
        )

        first = await orchestrator.submit(request)
        second = await orchestrator.submit(request)

        assert first.generation_id == second.generation_id
        assert second.created is False
        assert state.submits == 1

        with pytest.raises(AssetGenerationInvalid):
            await orchestrator.submit(
                _request(
                    project.project_id,
                    asset.asset_id,
                    brief.brief_id,
                    provider.provider_id,
                    model.model_id,
                    idempotency_key="hero-idle-1",
                    prompt="different prompt",
                )
            )


@pytest.mark.asyncio
async def test_generation_requires_approved_brief_and_matching_spec(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        state = FakeState()
        project, asset, brief, provider, model = await _seed(app, tmp_path)
        briefs = app.state.services.get("asset_brief_service", AssetBriefService)
        draft = await briefs.create(
            project_id=project.project_id,
            title="Draft brief",
            asset_category="IMAGE",
            asset_id=asset.asset_id,
            technical_constraints={"width": 512, "height": 512, "format": "png"},
        )
        orchestrator = _orchestrator(app, state)

        with pytest.raises(AssetBriefInvalid):
            await orchestrator.submit(
                _request(
                    project.project_id,
                    asset.asset_id,
                    draft.brief_id,
                    provider.provider_id,
                    model.model_id,
                )
            )

        with pytest.raises(AssetBriefInvalid):
            await orchestrator.submit(
                _request(
                    project.project_id,
                    asset.asset_id,
                    brief.brief_id,
                    provider.provider_id,
                    model.model_id,
                    parameters={"width": 1024, "height": 512, "format": "png"},
                )
            )
        assert state.submits == 0


@pytest.mark.asyncio
async def test_generation_unknown_state_is_persisted_and_not_retried(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        state = FakeState(mode="unknown")
        project, asset, brief, provider, model = await _seed(app, tmp_path)
        orchestrator = _orchestrator(app, state)
        request = _request(
            project.project_id,
            asset.asset_id,
            brief.brief_id,
            provider.provider_id,
            model.model_id,
            idempotency_key="unknown-1",
        )

        with pytest.raises(AssetGenerationUnknown):
            await orchestrator.submit(request)

        generation = await orchestrator.get(
            (await orchestrator.list_for_asset(project.project_id, asset.asset_id))[0].generation_id
        )
        assert generation.status == "UNKNOWN"
        assert state.submits == 1

        replay = await orchestrator.submit(request)
        assert replay.generation_id == generation.generation_id
        assert state.submits == 1


@pytest.mark.asyncio
async def test_provider_failure_is_recorded_as_failed(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        state = FakeState(mode="failed")
        project, asset, brief, provider, model = await _seed(app, tmp_path)
        orchestrator = _orchestrator(app, state)

        with pytest.raises(ModelCallFailed):
            await orchestrator.submit(
                _request(
                    project.project_id,
                    asset.asset_id,
                    brief.brief_id,
                    provider.provider_id,
                    model.model_id,
                )
            )
        views = await orchestrator.list_for_asset(project.project_id, asset.asset_id)
        assert views[0].status == "FAILED"


@pytest.mark.asyncio
async def test_async_generation_refresh_and_cancel(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        state = FakeState(mode="async")
        project, asset, brief, provider, model = await _seed(app, tmp_path)
        orchestrator = _orchestrator(app, state)
        base = _request(
            project.project_id,
            asset.asset_id,
            brief.brief_id,
            provider.provider_id,
            model.model_id,
            idempotency_key="async-1",
        )

        submitted = await orchestrator.submit(base)
        assert submitted.status == "RUNNING"
        assert submitted.provider_job_id == "job-async-1"

        refreshed = await orchestrator.refresh(submitted.generation_id)
        assert refreshed.status == "SUCCEEDED"
        assert refreshed.result_version_id is not None
        assert state.queries == 1

        pending = await orchestrator.submit(
            _request(
                project.project_id,
                asset.asset_id,
                brief.brief_id,
                provider.provider_id,
                model.model_id,
                idempotency_key="async-2",
                prompt="another hero",
            )
        )
        cancelled = await orchestrator.cancel(pending.generation_id)
        assert cancelled.status == "CANCELLED"
        assert state.cancels == 1


@pytest.mark.asyncio
async def test_unverified_capability_and_unknown_model_are_rejected(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        state = FakeState()
        project, asset, brief, provider, model = await _seed(
            app, tmp_path, capability=CAPABILITY_UNKNOWN
        )
        orchestrator = _orchestrator(app, state)

        with pytest.raises(AssetGenerationInvalid):
            await orchestrator.submit(
                _request(
                    project.project_id,
                    asset.asset_id,
                    brief.brief_id,
                    provider.provider_id,
                    model.model_id,
                )
            )
        with pytest.raises(ModelUnavailable):
            await orchestrator.submit(
                _request(
                    project.project_id,
                    asset.asset_id,
                    brief.brief_id,
                    provider.provider_id,
                    "mdl_missing",
                )
            )
        assert state.submits == 0


@pytest.mark.asyncio
async def test_disabled_model_is_rejected(tmp_path: Path) -> None:
    async with _running(tmp_path) as app:
        state = FakeState()
        project, asset, brief, provider, model = await _seed(app, tmp_path)
        registry = _registry(app)
        await registry.set_model_status(model.model_id, MODEL_DISABLED)
        orchestrator = _orchestrator(app, state)

        with pytest.raises(ModelUnavailable):
            await orchestrator.submit(
                _request(
                    project.project_id,
                    asset.asset_id,
                    brief.brief_id,
                    provider.provider_id,
                    model.model_id,
                )
            )


@pytest.mark.asyncio
async def test_budget_limits_block_generation_before_provider_call(
    tmp_path: Path,
) -> None:
    async with _running(tmp_path) as app:
        state = FakeState()
        project, asset, brief, provider, model = await _seed(app, tmp_path)
        orchestrator = _orchestrator(app, state)

        with pytest.raises(AssetGenerationInvalid):
            await orchestrator.submit(
                _request(
                    project.project_id,
                    asset.asset_id,
                    brief.brief_id,
                    provider.provider_id,
                    model.model_id,
                    output_count=2,
                    budget={"max_outputs": 1},
                )
            )
        assert state.submits == 0
        assert await orchestrator.list_for_asset(project.project_id, asset.asset_id) == []
