"""Bootstrap Token 管理（E2-Q1）。

首次注册与恢复性注册使用 ``data/bootstrap.token``。令牌只在启动时生成，
权限尽量收紧为 0600，且绝不写入日志；已存在时直接复用，保证重启后仍可用。
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from core.logging import get_logger, log_event
from core.security.tokens import constant_time_equals

DEFAULT_BOOTSTRAP_TOKEN_FILE = "bootstrap.token"
_TOKEN_BYTES = 32


class BootstrapTokenStore:
    def __init__(
        self,
        directory: str | Path,
        *,
        filename: str = DEFAULT_BOOTSTRAP_TOKEN_FILE,
        persist: bool = True,
    ) -> None:
        self._directory = Path(directory)
        self._filename = filename
        self._persist = persist
        self._token: str | None = None
        self._logger = get_logger("backend.auth")

    @property
    def path(self) -> Path:
        return self._directory / self._filename

    @property
    def token(self) -> str:
        if self._token is None:
            raise RuntimeError("Bootstrap Token 尚未初始化")
        return self._token

    def ensure(self) -> str:
        """读取已有令牌或生成新令牌；幂等。"""

        if self._token is not None:
            return self._token

        existing = self._read_existing() if self._persist else None
        if existing:
            self._token = existing
            log_event(
                self._logger,
                logging.INFO,
                "bootstrap_token_loaded",
                component="auth",
                route="startup",
            )
            return self._token

        self._token = secrets.token_urlsafe(_TOKEN_BYTES)
        if self._persist:
            self._write(self._token)
        log_event(
            self._logger,
            logging.INFO,
            "bootstrap_token_ready",
            component="auth",
            route="startup",
        )
        return self._token

    def verify(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        return constant_time_equals(self.token, candidate)

    def _read_existing(self) -> str | None:
        try:
            value = self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        return value or None

    def _write(self, token: str) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        descriptor = os.open(self.path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(token)
        finally:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                # Windows 上 chmod 语义有限；失败不影响功能，令牌仍不进日志
                pass
