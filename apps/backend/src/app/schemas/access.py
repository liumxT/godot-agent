"""项目访问请求模型（E2-T07）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
SESSION_ID_PATTERN = r"^ses_[a-z0-9]{12}$"


class ProjectAccessGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str = Field(pattern=PROJECT_ID_PATTERN)
    session_id: str = Field(
        pattern=SESSION_ID_PATTERN,
        description="被授权目标 Session；必须处于 ACTIVE 且未过期。",
    )
    access_level: Literal["owner", "editor", "viewer"]
    expires_at: datetime | None = Field(
        default=None,
        description="可选；缺省使用 project_access_ttl_seconds。",
    )
