"""客户端注册请求模型（E2-T06）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CLIENT_ID_PATTERN = r"^cli_[a-z0-9]{12}$"


class ClientRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_type: Literal["godot_editor", "admin", "tool"]
    client_name: str = Field(min_length=1, max_length=128)
    client_version: str | None = Field(default=None, max_length=64)
    godot_version: str | None = Field(default=None, max_length=64)
    platform: str | None = Field(default=None, max_length=64)
    client_id: str | None = Field(
        default=None,
        pattern=CLIENT_ID_PATTERN,
        description="可选；缺省由服务端生成，重复提交同一 ID 返回 CLIENT_EXISTS。",
    )
