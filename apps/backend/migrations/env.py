"""Alembic 运行环境。

迁移使用同步驱动（去掉 ``+aiosqlite``），应用运行时仍使用异步驱动。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from config.settings import load_settings

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    # 应用内运行时由 core.logging 统一管理日志，迁移不得接管 root logger
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    """优先使用调用方注入的 URL（测试），否则读取应用配置。"""

    configured = config.get_main_option("sqlalchemy.url")
    url = configured if configured else load_settings().database_url
    return url.replace("+aiosqlite", "")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # 应用内迁移传入运行时连接（含内存库的共享连接），避免另建引擎
    external = config.attributes.get("connection")
    if external is not None:
        context.configure(
            connection=external,
            target_metadata=None,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
