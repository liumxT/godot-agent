"""配置加载唯一入口。

所有配置必须经 load_settings() 进入系统，禁止散落读取 os.environ。
密钥（API Key、Token、密码）不属于 Settings，统一通过
``infrastructure.secrets`` 访问操作系统凭证库。
"""

from __future__ import annotations

import ipaddress
from enum import Enum

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.errors import ConfigError


class Environment(str, Enum):
    development = "development"
    test = "test"
    production = "production"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GODOT_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用配置
    app_name: str = "godot-ai-backend"
    app_version: str = "0.1.0"
    environment: Environment = Environment.development

    # 网络配置：只允许回环地址
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)

    # 数据配置
    data_dir: str = "data"
    # 必填项：缺失时启动直接失败，避免以错误状态运行
    database_url: str

    # 日志配置
    log_level: LogLevel = LogLevel.INFO
    log_dir: str = "logs"

    # 模型配置：具体 Provider 在 E4 定义，E0 只保留选择位
    model_provider: str = "none"

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        host = value.strip().lower()
        if host == "localhost":
            return host
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("host 必须是回环地址（127.0.0.1 / ::1 / localhost）") from exc
        if not address.is_loopback:
            raise ValueError("host 必须是回环地址（127.0.0.1 / ::1 / localhost）")
        return host

    @field_validator("database_url")
    @classmethod
    def _sqlite_only(cls, value: str) -> str:
        if not value.startswith("sqlite"):
            raise ValueError("database_url 必须使用 SQLite")
        return value

    @field_validator("data_dir", "log_dir")
    @classmethod
    def _non_empty_dir(cls, value: str) -> str:
        directory = value.strip()
        if not directory:
            raise ValueError("目录配置不能为空")
        return directory

    @field_validator("model_provider")
    @classmethod
    def _non_empty_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if not provider:
            raise ValueError("model_provider 不能为空，未启用时使用 none")
        return provider


def load_settings(**overrides: object) -> Settings:
    """加载并校验配置；失败时抛出带明确信息的 ConfigError。"""

    try:
        return Settings(**overrides)
    except ValidationError as exc:
        missing = [str(item["loc"][0]) for item in exc.errors() if item["type"] == "missing"]
        detail = "缺少必填配置: " + ", ".join(missing) if missing else "配置格式非法"
        raise ConfigError(detail, details={"errors": exc.errors(include_url=False)}) from exc
