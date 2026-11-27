# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 构建配置：Godot AI Agent 后端（含 E12 产品化模块）。

构建（在 apps/backend 下）：
    .venv/Scripts/python.exe -m PyInstaller godot-ai-backend.spec --noconfirm

入口为 src/app/main.py；migrations 与 packages/contracts 以数据形式打包，
供 Alembic 运行时迁移与契约校验使用。product 等模块经导入链自动收集。
"""

from pathlib import Path

BACKEND_ROOT = Path(SPECPATH)
REPO_ROOT = BACKEND_ROOT.parent.parent

block_cipher = None

a = Analysis(
    [str(BACKEND_ROOT / "src" / "app" / "main.py")],
    pathex=[str(BACKEND_ROOT / "src")],
    binaries=[],
    datas=[
        (str(BACKEND_ROOT / "migrations"), "migrations"),
        (str(REPO_ROOT / "packages" / "contracts"), "packages/contracts"),
    ],
    hiddenimports=[
        "alembic.ddl.sqlite",
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.aiosqlite",
        "aiosqlite",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="godot-ai-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
