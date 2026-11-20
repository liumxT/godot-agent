"""Bridge 握手 payload 模型（E3-M3）。

控制帧外层由 ``app.ws.protocol`` 校验；这里只约束 HELLO / AUTH_RESPONSE
的 payload，拒绝额外字段，避免客户端夹带未定义信息。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EDITOR_STATUS = Literal["READY", "IMPORTING", "ERROR", "UNKNOWN"]
PROJECT_STATUS = Literal["READY", "MISSING", "INVALID"]
RUN_STATUS = Literal["STOPPED", "RUNNING", "PAUSED", "UNKNOWN"]
IMPORT_STATUS = Literal["IDLE", "IMPORTING", "FAILED", "UNKNOWN"]
RUNTIME_STATUS = Literal["RUNNING", "STOPPED", "CRASHED"]
BUILD_MODE = Literal["debug", "release", "editor"]


class ProjectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = Field(min_length=1, max_length=1024)
    name: str | None = Field(default=None, max_length=256)
    godot_version: str | None = Field(default=None, max_length=32)


class ResumePayload(BaseModel):
    """断线重连时携带的原 Session 凭证（E3-T12）；服务端以库中状态为准。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64)
    session_token: str = Field(min_length=1, max_length=128)


class HelloPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1, max_length=64)
    editor_instance_id: str = Field(min_length=1, max_length=128)
    plugin_version: str = Field(min_length=1, max_length=32)
    godot_version: str = Field(min_length=1, max_length=32)
    project: ProjectPayload
    resume: ResumePayload | None = None


class AuthResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=1, max_length=64)
    proof: str = Field(min_length=1, max_length=128)


class UnsavedResourcePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    resource_type: str | None = Field(default=None, max_length=64)


class EditorStatePayload(BaseModel):
    """编辑器状态（E3-T15），字段与 ``editor-state.schema.json`` 对齐。"""

    model_config = ConfigDict(extra="forbid")

    editor_status: EDITOR_STATUS
    project_status: PROJECT_STATUS
    active_scene: str | None = Field(default=None, max_length=1024)
    current_selection: list[str] = Field(default_factory=list, max_length=256)
    unsaved_resources: list[UnsavedResourcePayload] = Field(default_factory=list, max_length=256)
    run_status: RUN_STATUS = "UNKNOWN"
    import_status: IMPORT_STATUS = "UNKNOWN"


class StateReportPayload(EditorStatePayload):
    """``editor.state.report`` 的上报载荷：状态 + 发生变化的字段名。"""

    changed: list[str] = Field(default_factory=list, max_length=16)


class RuntimeHelloPayload(BaseModel):
    """Runtime 握手载荷（E3-T16）；项目身份以指纹匹配已登记记录。"""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1, max_length=64)
    runtime_instance_id: str = Field(pattern=r"^rti_[0-9a-f]{12}$")
    project_root: str = Field(min_length=1, max_length=1024)
    project_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    process_id: int = Field(ge=1)
    started_at: datetime
    godot_version: str = Field(min_length=1, max_length=32)
    build_mode: BUILD_MODE = "debug"
    status: RUNTIME_STATUS = "RUNNING"


class RuntimeReportPayload(BaseModel):
    """Runtime 周期上报（E3-T16），只允许状态与时间戳。"""

    model_config = ConfigDict(extra="forbid")

    runtime_instance_id: str = Field(pattern=r"^rti_[0-9a-f]{12}$")
    status: RUNTIME_STATUS
    timestamp: datetime
