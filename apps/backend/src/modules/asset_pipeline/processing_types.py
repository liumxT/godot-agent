"""资产处理流水线基础类型（E8-T09）。

处理图是有向无环图，节点只通过公开的 Processor 契约执行：

- 图结构、依赖、环与输出唯一性在提交前校验；
- 每个节点记录处理器 ID、版本、输入/输出 Hash、参数、耗时与资源占用；
- 处理器只能读取内存中的产物，不能自行访问任意路径；
- 像素数、文件大小、产物数量与执行时间均受限制。
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from core.errors import AssetProcessingInvalid

_NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_INPUT_ALIAS = "input"


@dataclass(frozen=True, slots=True)
class ProcessingArtifact:
    data: bytes
    format: str
    filename_hint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise AssetProcessingInvalid("处理产物不能为空")
        if not self.format.strip():
            raise AssetProcessingInvalid("处理产物缺少格式")
        if not isinstance(self.metadata, Mapping):
            raise AssetProcessingInvalid("处理产物元数据必须是对象")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True, slots=True)
class ProcessingPayload:
    artifacts: tuple[ProcessingArtifact, ...]

    def __post_init__(self) -> None:
        if not self.artifacts:
            raise AssetProcessingInvalid("处理输入/输出不能为空")

    def merged(self) -> ProcessingPayload:
        return self


@dataclass(frozen=True, slots=True)
class ProcessingLimits:
    max_input_bytes: int = 200 * 1024 * 1024
    max_pixels: int = 16_000_000
    max_artifacts: int = 256
    max_output_bytes: int = 400 * 1024 * 1024
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_input_bytes <= 0 or self.max_output_bytes <= 0:
            raise AssetProcessingInvalid("处理大小限制必须大于 0")
        if self.max_pixels <= 0 or self.max_artifacts <= 0:
            raise AssetProcessingInvalid("处理资源限制必须大于 0")
        if self.timeout_seconds <= 0:
            raise AssetProcessingInvalid("处理超时限制必须大于 0")


@dataclass(slots=True)
class ProcessingContext:
    project_id: str
    asset_id: str
    limits: ProcessingLimits
    deadline: float

    @classmethod
    def create(
        cls, project_id: str, asset_id: str, limits: ProcessingLimits
    ) -> ProcessingContext:
        return cls(
            project_id=project_id,
            asset_id=asset_id,
            limits=limits,
            deadline=time.monotonic() + limits.timeout_seconds,
        )

    def check_deadline(self) -> None:
        if time.monotonic() > self.deadline:
            raise AssetProcessingInvalid(
                "处理超时", details={"timeout_seconds": self.limits.timeout_seconds}
            )

    def check_pixels(self, width: int, height: int) -> None:
        pixels = max(width, 0) * max(height, 0)
        if pixels > self.limits.max_pixels:
            raise AssetProcessingInvalid(
                "图像像素数超过处理限制",
                details={"width": width, "height": height, "max_pixels": self.limits.max_pixels},
            )

    def check_artifacts(self, count: int) -> None:
        if count > self.limits.max_artifacts:
            raise AssetProcessingInvalid(
                "产物数量超过处理限制",
                details={"artifacts": count, "max_artifacts": self.limits.max_artifacts},
            )


class ProcessingProcessor(Protocol):
    processor_id: str
    version: str

    def validate(self, parameters: Mapping[str, Any]) -> None: ...

    def process(
        self,
        payload: ProcessingPayload,
        parameters: Mapping[str, Any],
        context: ProcessingContext,
    ) -> ProcessingPayload: ...


class ProcessingProcessorRegistry:
    def __init__(self) -> None:
        self._processors: dict[str, ProcessingProcessor] = {}

    def register(self, processor: ProcessingProcessor) -> None:
        if not processor.processor_id.strip():
            raise AssetProcessingInvalid("处理器 ID 不能为空")
        if processor.processor_id in self._processors:
            raise AssetProcessingInvalid(
                "处理器重复注册", details={"processor_id": processor.processor_id}
            )
        self._processors[processor.processor_id] = processor

    def get(self, processor_id: str) -> ProcessingProcessor:
        processor = self._processors.get(processor_id)
        if processor is None:
            raise AssetProcessingInvalid(
                "处理器未注册", details={"processor_id": processor_id}
            )
        return processor

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._processors))


@dataclass(frozen=True, slots=True)
class ProcessingNode:
    node_id: str
    processor: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = (_INPUT_ALIAS,)

    def __post_init__(self) -> None:
        if not _NODE_ID_PATTERN.match(self.node_id):
            raise AssetProcessingInvalid(
                "处理节点 ID 非法", details={"node_id": self.node_id}
            )
        if self.node_id == _INPUT_ALIAS:
            raise AssetProcessingInvalid("处理节点不能使用保留 ID input")
        if not self.processor.strip():
            raise AssetProcessingInvalid(
                "处理节点缺少 processor", details={"node_id": self.node_id}
            )
        if not isinstance(self.parameters, Mapping):
            raise AssetProcessingInvalid(
                "处理节点参数必须是对象", details={"node_id": self.node_id}
            )
        if not self.depends_on:
            raise AssetProcessingInvalid(
                "处理节点至少需要一个输入", details={"node_id": self.node_id}
            )


@dataclass(frozen=True, slots=True)
class ProcessingGraph:
    nodes: tuple[ProcessingNode, ...]
    terminal: str

    def __post_init__(self) -> None:
        if not self.nodes:
            raise AssetProcessingInvalid("处理图不能为空")

    def ordered(self) -> tuple[ProcessingNode, ...]:
        by_id = {node.node_id: node for node in self.nodes}
        indegree = {node.node_id: 0 for node in self.nodes}
        adjacency: dict[str, list[str]] = {node.node_id: [] for node in self.nodes}
        for node in self.nodes:
            for dependency in node.depends_on:
                if dependency == _INPUT_ALIAS:
                    continue
                if dependency not in by_id:
                    raise AssetProcessingInvalid(
                        "处理节点依赖不存在",
                        details={"node_id": node.node_id, "dependency": dependency},
                    )
                indegree[node.node_id] += 1
                adjacency[dependency].append(node.node_id)
        ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
        ordered: list[ProcessingNode] = []
        while ready:
            node_id = ready.pop(0)
            ordered.append(by_id[node_id])
            for dependent in sorted(adjacency[node_id]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort()
        if len(ordered) != len(self.nodes):
            raise AssetProcessingInvalid("处理图存在循环依赖")
        return tuple(ordered)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": node.node_id,
                    "processor": node.processor,
                    "parameters": dict(node.parameters),
                    "depends_on": list(node.depends_on),
                }
                for node in self.nodes
            ]
        }


def parse_processing_graph(raw: Mapping[str, Any] | list[Any]) -> ProcessingGraph:
    if not isinstance(raw, Mapping):
        raise AssetProcessingInvalid("处理图必须是对象")
    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise AssetProcessingInvalid("处理图必须包含非空 nodes")
    nodes: list[ProcessingNode] = []
    seen: set[str] = set()
    for item in raw_nodes:
        if not isinstance(item, Mapping):
            raise AssetProcessingInvalid("处理节点必须是对象")
        try:
            node = ProcessingNode(
                node_id=str(item.get("id", "")),
                processor=str(item.get("processor", "")),
                parameters=dict(item.get("parameters") or {}),
                depends_on=tuple(item.get("depends_on") or ["input"]),
            )
        except (TypeError, ValueError) as error:
            raise AssetProcessingInvalid("处理节点格式非法") from error
        if node.node_id in seen:
            raise AssetProcessingInvalid(
                "处理节点 ID 重复", details={"node_id": node.node_id}
            )
        seen.add(node.node_id)
        nodes.append(node)
    dependents: dict[str, int] = {node.node_id: 0 for node in nodes}
    for node in nodes:
        for dependency in node.depends_on:
            if dependency in dependents:
                dependents[dependency] += 1
    terminals = [node_id for node_id, count in dependents.items() if count == 0]
    if len(terminals) != 1:
        raise AssetProcessingInvalid(
            "处理图必须只有一个输出节点", details={"terminals": terminals}
        )
    graph = ProcessingGraph(nodes=tuple(nodes), terminal=terminals[0])
    graph.ordered()
    return graph


@dataclass(frozen=True, slots=True)
class StepRecord:
    node_id: str
    processor_id: str
    processor_version: str
    input_hash: str
    output_hash: str
    parameters: Mapping[str, Any]
    execution_status: str
    resource_usage: Mapping[str, Any]
    started_at: datetime
    completed_at: datetime

    def to_mapping(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "processor_id": self.processor_id,
            "processor_version": self.processor_version,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "parameters": dict(self.parameters),
            "execution_status": self.execution_status,
            "resource_usage": dict(self.resource_usage),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }
