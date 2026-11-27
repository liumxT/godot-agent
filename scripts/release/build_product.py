"""产品发布构建与校验（E12-T19）。

生成 GA 交付目录结构、产品/组件清单、契约清单、兼容性矩阵与 SBOM，
并对关键交付物做存在性校验。脚本只组装与校验，不替代 PyInstaller 打包、
Godot 插件导出或安装器编译。

用法::

    python scripts/release/build_product.py --output release
    python scripts/release/build_product.py --check

输出目录结构::

    release/
      README.md
      backend/            # PyInstaller 产物（由打包步骤写入）
      godot_plugin/       # addons/godot_ai_agent（由插件导出步骤写入）
      installers/windows|macos|linux/
      documentation/      # 文档入口
      manifests/          # product / component / compatibility
      security/sbom/      # SBOM
      verification/       # GA 验收证据
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "apps" / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from modules.product.compatibility import matrix
from modules.product.versioning import (
    COMPATIBILITY_MATRIX_VERSION,
    COMPONENT_INDEX,
    COMPONENTS,
    CONTRACTS,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    component_manifest,
    contract_manifest,
    declared_component_versions,
)

REQUIRED_PATHS = (
    "apps/backend/src/app/main.py",
    "apps/backend/migrations/versions/000033_e12_product_core.py",
    "apps/godot-plugin/addons/godot_ai_agent/plugin.cfg",
    "packages/contracts/errors/error-codes.json",
    "docs/README.md",
    "docs/05-product/user-guide.md",
    "docs/04-operations/runbooks.md",
)

SUBDIRS = (
    "backend",
    "godot_plugin",
    "installers/windows",
    "installers/macos",
    "installers/linux",
    "documentation",
    "manifests",
    "security/sbom",
    "verification",
)

# 组装（assemble）源：已构建产物/文档/证据，源存在才复制，缺失则记入 skipped。
BACKEND_EXE_SRC = ROOT / "artifacts" / "dist-e12" / "godot-ai-backend.exe"
BACKEND_LAUNCHER_SRC = ROOT / "scripts" / "release" / "packaging" / "Start-Backend.cmd"
PLUGIN_SRC = ROOT / "apps" / "godot-plugin" / "addons" / "godot_ai_agent"
ASSEMBLE_DOCS = (
    "docs/05-product/user-guide.md",
    "docs/05-product/usage-manual.md",
    "docs/05-product/developer-guide.md",
    "docs/04-operations/runbooks.md",
    "docs/05-product/release-notes/v1.0.0.md",
)
VERIFICATION_SRC = {
    "ci-report.md": ROOT / "artifacts" / "ci-report.md",
    "full-test-report.md": ROOT / "artifacts" / "full-test-report.md",
}


def assemble(output: Path) -> dict[str, object]:
    """把已构建的产物、插件、文档与 GA 证据复制进 release 目录。

    源缺失时跳过并记录，不强制失败（exe 可能尚未打包）。本步骤只做组装，
    不替代 PyInstaller 打包、插件导出或安装器编译。
    """

    copied: list[str] = []
    skipped: list[str] = []

    def _copy_file(src: Path, dest: Path) -> None:
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied.append(str(dest.relative_to(output)))
        else:
            skipped.append(str(src.relative_to(ROOT)))

    # 后端可执行文件与启动脚本
    _copy_file(BACKEND_EXE_SRC, output / "backend" / "godot-ai-backend.exe")
    _copy_file(BACKEND_LAUNCHER_SRC, output / "backend" / "Start-Backend.cmd")

    # Godot 插件（整目录）
    if PLUGIN_SRC.exists():
        dest = output / "godot_plugin" / "addons" / "godot_ai_agent"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(PLUGIN_SRC, dest)
        copied.append("godot_plugin/addons/godot_ai_agent")
    else:
        skipped.append(str(PLUGIN_SRC.relative_to(ROOT)))

    # 文档
    for rel in ASSEMBLE_DOCS:
        _copy_file(ROOT / rel, output / "documentation" / Path(rel).name)

    # GA 验收证据
    for name, src in VERIFICATION_SRC.items():
        _copy_file(src, output / "verification" / name)

    return {"copied": copied, "skipped": skipped}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sbom() -> dict[str, object]:
    packages = [
        {"name": item.metadata["Name"], "version": item.version}
        for item in metadata.distributions()
        if item.metadata["Name"]
    ]
    packages.sort(key=lambda item: (item["name"].lower(), item["version"]))
    digest = hashlib.sha256(
        json.dumps(packages, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "format": "CycloneDX-lite",
        "component": {"name": PRODUCT_NAME, "version": PRODUCT_VERSION},
        "count": len(packages),
        "sha256": digest,
        "packages": packages,
    }


def validate_tree() -> list[str]:
    problems = [
        f"缺少交付物: {path}" for path in REQUIRED_PATHS if not (ROOT / path).exists()
    ]
    problems += [
        f"组件未登记: {item.component_id}"
        for item in COMPONENTS
        if item.component_id not in COMPONENT_INDEX
    ]
    return problems


def build(output: Path) -> dict[str, object]:
    problems = validate_tree()
    if problems:
        raise SystemExit("交付物校验失败:\n- " + "\n- ".join(problems))

    for name in SUBDIRS:
        (output / name).mkdir(parents=True, exist_ok=True)

    manifests = output / "manifests"
    product_manifest = {
        "product_name": PRODUCT_NAME,
        "product_version": PRODUCT_VERSION,
        "version_domain": "product",
        "game_artifact_version_domain": "game_artifact",
        "compatibility_matrix_version": COMPATIBILITY_MATRIX_VERSION,
        "build": {
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.machine()}",
            "created_at": datetime.now(UTC).isoformat(),
            "channel": "STABLE",
        },
        **component_manifest(),
    }
    contract = contract_manifest()
    matrix_payload = matrix()
    sbom = _sbom()

    files = {
        "manifests/product_manifest.json": product_manifest,
        "manifests/component_manifest.json": {
            "components": product_manifest["components"],
            "contracts": contract,
            "declared_versions": declared_component_versions(),
        },
        "manifests/compatibility_matrix.json": matrix_payload,
        "manifests/contracts.json": contract,
        "security/sbom/sbom.json": sbom,
    }
    checksums: dict[str, str] = {}
    for name, payload in files.items():
        target = output / name
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        checksums[name] = _sha256(target)

    manifest = {
        "files": checksums,
        "sbom": {
            "path": "security/sbom/sbom.json",
            "sha256": checksums["security/sbom/sbom.json"],
            "count": sbom["count"],
        },
        "components": len(COMPONENTS),
        "contracts": len(CONTRACTS),
    }
    (manifests / "checksums.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest["assemble"] = assemble(output)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="组装并校验产品发布目录")
    parser.add_argument("--output", default="release", help="输出目录，默认 release/")
    parser.add_argument("--check", action="store_true", help="仅校验交付物，不写文件")
    args = parser.parse_args()

    problems = validate_tree()
    if problems:
        for item in problems:
            print("[missing]", item)
        return 1
    if args.check:
        print(
            json.dumps(
                {
                    "product": PRODUCT_NAME,
                    "version": PRODUCT_VERSION,
                    "components": len(COMPONENTS),
                    "contracts": len(CONTRACTS),
                    "status": "OK",
                },
                ensure_ascii=False,
            )
        )
        return 0

    result = build((ROOT / args.output).resolve())
    print(json.dumps({"status": "BUILT", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
