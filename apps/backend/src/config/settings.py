"""配置加载唯一入口。

所有配置必须经 load_settings() 进入系统，禁止散落读取 os.environ。
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.errors import ConfigError


class Environment(str, Enum):
    development = "development"
    test = "test"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GODOT_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "godot-ai-backend"
    app_version: str = "0.1.0"
    environment: Environment = Environment.development
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    log_level: str = "INFO"
    # 必填项：缺失时启动直接失败，避免以错误状态运行
    database_url: str


def load_settings(**overrides: object) -> Settings:
    """加载并校验配置；失败时抛出带明确信息的 ConfigError。"""

    try:
        return Settings(**overrides)
    except ValidationError as exc:
        missing = [str(item["loc"][0]) for item in exc.errors() if item["type"] == "missing"]
        detail = "缺少必填配置: " + ", ".join(missing) if missing else "配置格式非法"
        raise ConfigError(detail, details={"errors": exc.errors(include_url=False)}) from exc
