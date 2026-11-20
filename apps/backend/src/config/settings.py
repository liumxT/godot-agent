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

    # 事件派发：事务只写 Outbox，提交后轮询派发（E1-Q5）
    event_poll_interval_ms: int = Field(default=100, ge=10, le=60000)
    event_batch_size: int = Field(default=50, ge=1, le=500)
    event_max_retries: int = Field(default=5, ge=0, le=100)

    # 备份：默认与数据库同目录下的 backups/，按数量保留最近 N 份
    backup_dir: str | None = None
    backup_retention: int = Field(default=10, ge=1, le=1000)

    # 认证与 Token（E2-T03 / T04）
    auth_challenge_ttl_seconds: int = Field(default=60, ge=0, le=3600)
    access_token_ttl_seconds: int = Field(default=600, ge=0, le=86400)
    token_retention_days: int = Field(default=7, ge=1, le=365)
    auth_cleanup_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    rate_limit_auth_per_minute: int = Field(default=10, ge=1, le=10000)
    bootstrap_token_file: str = "bootstrap.token"

    # Session 与项目访问（E2-T05 / T07）
    session_ttl_seconds: int = Field(default=28800, ge=0, le=86400)
    session_max_ttl_seconds: int = Field(default=86400, ge=0, le=604800)
    session_retention_days: int = Field(default=7, ge=1, le=365)
    project_access_ttl_seconds: int = Field(default=86400, ge=0, le=31536000)

    # 请求保护（E2-T09 / T10）
    request_max_body_bytes: int = Field(default=1048576, ge=1, le=67108864)
    request_timeout_seconds: int = Field(default=30, ge=1, le=600)
    rate_limit_default_per_minute: int = Field(default=120, ge=1, le=100000)
    rate_limit_max_concurrency: int = Field(default=20, ge=1, le=1000)

    # 审计（E2-T11）：敏感操作审计失败默认拒绝
    audit_fail_closed: bool = True

    # E3 Editor/Runtime Bridge
    bridge_enabled: bool = True
    bridge_ws_path_editor: str = "/api/v1/ws/editor"
    bridge_ws_path_runtime: str = "/api/v1/ws/runtime"
    bridge_handshake_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120)
    bridge_heartbeat_interval_seconds: int = Field(default=10, ge=1, le=300)
    bridge_heartbeat_timeout_seconds: int = Field(default=30, ge=1, le=600)
    bridge_lease_ttl_seconds: int = Field(default=45, ge=1, le=3600)
    bridge_request_timeout_seconds: int = Field(default=15, ge=1, le=120)
    bridge_ws_max_message_bytes: int = Field(default=262144, ge=1024, le=4194304)
    bridge_outbound_queue_max: int = Field(default=64, ge=1, le=1024)
    bridge_event_ack_timeout_seconds: int = Field(default=30, ge=1, le=600)
    bridge_event_retention_days: int = Field(default=7, ge=1, le=365)
    bridge_snapshot_ttl_seconds: int = Field(default=900, ge=1, le=86400)
    bridge_runtime_heartbeat_seconds: int = Field(default=5, ge=1, le=60)
    bridge_snapshot_keep_per_session: int = Field(default=5, ge=1, le=100)
    bridge_runtime_timeout_seconds: int = Field(default=20, ge=1, le=600)
    bridge_rate_limit_per_minute: int = Field(default=240, ge=1, le=100000)

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

    @field_validator("data_dir", "log_dir", "bootstrap_token_file")
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
