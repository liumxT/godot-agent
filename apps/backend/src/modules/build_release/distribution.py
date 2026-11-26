"""分发适配器基础（E10-T16）。

首期只提供本地交付适配器：

- 目标目录必须存在且可写；
- 只复制已校验的交付包/制品，不修改源文件；
- 复制完成后重新计算哈希，验证失败即失败；
- 交付记录保留可追溯的交付引用。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from core.errors import DistributionInvalid
from modules.build_release.adapter import file_digest
from modules.build_release.models import (
    CHANNEL_LOCAL,
    CHANNEL_LOCAL_EXPORT,
    CHANNEL_USER_DOWNLOAD,
    CHANNEL_USER_OUTPUT_DIR,
    DIST_FAILED,
    DIST_SUCCEEDED,
    DIST_UNKNOWN,
)


@dataclass(frozen=True, slots=True)
class DistributionCapabilities:
    channel: str
    supported: bool
    requires_authorization: bool
    supports_withdraw: bool
    description: str


@dataclass(frozen=True, slots=True)
class DistributionResult:
    status: str
    reference: str = ""
    external_operation_id: str = ""
    digest: str = ""
    detail: str = ""


class DistributionAdapter(Protocol):
    channel: str

    def get_capabilities(self) -> DistributionCapabilities: ...

    async def prepare_distribution(self, *, target_reference: str) -> None: ...

    async def submit_release(
        self, *, source_path: Path, target_reference: str, version: str
    ) -> DistributionResult: ...

    async def verify_distribution(self, *, reference: str, expected_digest: str) -> bool: ...

    async def withdraw_release(self, *, reference: str) -> DistributionResult: ...


class LocalDistributionAdapter:
    """本地交付：把文件复制到用户选择的输出目录。"""

    channel = CHANNEL_LOCAL_EXPORT

    def get_capabilities(self) -> DistributionCapabilities:
        return DistributionCapabilities(
            channel=self.channel,
            supported=True,
            requires_authorization=False,
            supports_withdraw=True,
            description="本地交付到用户选择的目录",
        )

    async def prepare_distribution(self, *, target_reference: str) -> None:
        target = Path(target_reference)
        if not target.exists() or not target.is_dir():
            raise DistributionInvalid("交付目标目录不存在", details={"target": target_reference})
        if not os.access(target, os.W_OK):
            raise DistributionInvalid("交付目标目录不可写", details={"target": target_reference})

    async def submit_release(
        self, *, source_path: Path, target_reference: str, version: str
    ) -> DistributionResult:
        if not source_path.exists() or not source_path.is_file():
            return DistributionResult(
                status=DIST_FAILED, detail=f"源文件不存在: {source_path.name}"
            )
        target_dir = Path(target_reference)
        destination = target_dir / source_path.name
        try:
            shutil.copy2(source_path, destination)
        except OSError as exc:
            return DistributionResult(status=DIST_UNKNOWN, detail=f"复制失败: {exc}")
        digest = file_digest(destination)
        return DistributionResult(
            status=DIST_SUCCEEDED,
            reference=str(destination.resolve()),
            digest=digest,
            detail=f"已交付 {version}",
        )

    async def verify_distribution(self, *, reference: str, expected_digest: str) -> bool:
        path = Path(reference)
        if not path.exists() or not path.is_file():
            return False
        if not expected_digest:
            return True
        return file_digest(path) == expected_digest

    async def withdraw_release(self, *, reference: str) -> DistributionResult:
        path = Path(reference)
        if path.exists() and path.is_file():
            try:
                path.unlink()
            except OSError as exc:
                return DistributionResult(status=DIST_UNKNOWN, detail=f"撤回失败: {exc}")
        return DistributionResult(status=DIST_SUCCEEDED, reference=reference, detail="已撤回")


class DistributionAdapterRegistry:
    """按渠道注册分发适配器；未实现渠道不会显示为可用。"""

    def __init__(self, adapters: list[DistributionAdapter] | None = None) -> None:
        self._adapters: dict[str, DistributionAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: DistributionAdapter) -> None:
        self._adapters[adapter.channel] = adapter

    def get(self, channel: str) -> DistributionAdapter:
        adapter = self._adapters.get(channel)
        if adapter is None:
            raise DistributionInvalid("分发渠道未实现或不可用", details={"channel": channel})
        return adapter

    def capabilities(self) -> list[DistributionCapabilities]:
        return [adapter.get_capabilities() for adapter in self._adapters.values()]


def build_default_registry() -> DistributionAdapterRegistry:
    local = LocalDistributionAdapter()
    aliases = (CHANNEL_LOCAL, CHANNEL_USER_DOWNLOAD, CHANNEL_USER_OUTPUT_DIR)
    registry = DistributionAdapterRegistry([local])
    for channel in aliases:
        registry.register(_LocalAliasAdapter(local, channel))
    return registry


class _LocalAliasAdapter:
    """把本地交付适配器映射到其他本地渠道名称。"""

    def __init__(self, delegate: LocalDistributionAdapter, channel: str) -> None:
        self._delegate = delegate
        self.channel = channel

    def get_capabilities(self) -> DistributionCapabilities:
        base = self._delegate.get_capabilities()
        return DistributionCapabilities(
            channel=self.channel,
            supported=base.supported,
            requires_authorization=base.requires_authorization,
            supports_withdraw=base.supports_withdraw,
            description=base.description,
        )

    async def prepare_distribution(self, *, target_reference: str) -> None:
        await self._delegate.prepare_distribution(target_reference=target_reference)

    async def submit_release(
        self, *, source_path: Path, target_reference: str, version: str
    ) -> DistributionResult:
        return await self._delegate.submit_release(
            source_path=source_path, target_reference=target_reference, version=version
        )

    async def verify_distribution(self, *, reference: str, expected_digest: str) -> bool:
        return await self._delegate.verify_distribution(
            reference=reference, expected_digest=expected_digest
        )

    async def withdraw_release(self, *, reference: str) -> DistributionResult:
        return await self._delegate.withdraw_release(reference=reference)
