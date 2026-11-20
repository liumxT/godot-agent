"""管理界面路由测试（E4-T23）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bootstrap.application import create_app
from config.settings import load_settings


def _settings(tmp_path: Path):
    return load_settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'ui.db').as_posix()}",
        environment="test",
        data_dir=str(tmp_path),
    )


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(_settings(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def test_management_page_is_served_without_credentials(client) -> None:
    response = client.get("/api/v1/manage")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "Godot AI Agent 管理" in body
    assert "/api/v1" in body
    # 页面不允许内置任何令牌或密钥（占位提示不算）。
    assert "Bearer gda_" not in body
    assert "Bearer gds_" not in body
    assert "client_secret" not in body


def test_management_data_requires_authentication(client) -> None:
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/approvals?project_id=prj_demo").status_code == 401
