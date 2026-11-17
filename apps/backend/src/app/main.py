"""应用入口。

启动方式：
    python -m app.main
"""

from __future__ import annotations

import uvicorn

from bootstrap.application import create_app
from config.settings import load_settings

app = create_app()


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
