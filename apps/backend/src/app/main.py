"""应用入口。

启动方式：
    python -m app.main
    python -m app.main --migrate   # 升级数据库到最新版本后退出
"""

from __future__ import annotations

import json
import sys

import uvicorn

from bootstrap.application import create_app
from config.settings import load_settings

app = create_app()


def _migrate() -> int:
    from infrastructure.database.manager import upgrade_to_head

    result = upgrade_to_head(load_settings())
    print(
        json.dumps(
            {
                "from_revision": result.from_revision,
                "to_revision": result.to_revision,
                "changed": result.changed,
                "backup": str(result.backup_path) if result.backup_path else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> None:
    if "--migrate" in sys.argv[1:]:
        raise SystemExit(_migrate())

    settings = load_settings()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
