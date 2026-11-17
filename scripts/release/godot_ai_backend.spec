# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（E0-T02 打包 spike / E10 复用）。

构建（仓库根目录执行）：
    python -m PyInstaller --noconfirm \
        --distpath artifacts/dist --workpath artifacts/build \
        scripts/release/godot_ai_backend.spec

单文件对照构建：
    $env:GODOT_AI_PACK_ONEFILE='1'
    python -m PyInstaller ...（同上）

打包后运行时资源位于解包目录，代码通过 sys._MEIPASS 定位
（见 shared/contracts.py 与 infrastructure/database/manager.py）。
"""

import os
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parents[1]
BACKEND = ROOT / "apps" / "backend"
ONEFILE = os.environ.get("GODOT_AI_PACK_ONEFILE") == "1"

hiddenimports = [
    # Alembic 通过方言与脚本动态加载，静态分析发现不了
    "alembic.ddl.sqlite",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "aiosqlite",
    # uvicorn 的协议实现按配置动态导入
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

datas = [
    (str(BACKEND / "migrations"), "migrations"),
    (str(ROOT / "packages" / "contracts"), "packages/contracts"),
]

a = Analysis(
    [str(BACKEND / "src" / "app" / "main.py")],
    pathex=[str(BACKEND / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="godot-ai-backend",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="godot-ai-backend",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="godot-ai-backend",
    )
