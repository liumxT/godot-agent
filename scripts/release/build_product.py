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
    problems = [f"缺少交付物: {path}" for path in REQUIRED_PATHS if not (ROOT / path).exists()]
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
