# 产品发布目录

本目录由 `scripts/release/build_product.py` 生成或组装，二进制产物不入库（仅 `README.md` 入库）。

```powershell
python scripts/release/build_product.py --check           # 仅校验交付物
python scripts/release/build_product.py --output release  # 生成清单/SBOM 并组装产物
```

`--output` 会生成清单、契约、兼容性矩阵与 SBOM，并把已构建产物组装进目录：
后端 `godot-ai-backend.exe` 与启动脚本（来自 `artifacts/dist-e12`）、Godot 插件
（`godot_plugin/addons/godot_ai_agent`）、核心文档（`documentation/`）、GA 证据
（`verification/`：CI 报告、完整测试报告、安装器冒烟 `installer-smoke.json`）。
源缺失时跳过并记录于输出 `assemble.skipped`。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `backend/` | 后端打包产物（PyInstaller） |
| `godot_plugin/` | `addons/godot_ai_agent` 插件 |
| `installers/windows|macos|linux/` | 各平台安装器 |
| `documentation/` | 用户指南、开发者指南与运维手册入口 |
| `manifests/` | 产品清单、组件清单、契约清单、兼容性矩阵与校验和 |
| `security/sbom/` | SBOM |
| `verification/` | GA 验收证据（测试、兼容性、安装冒烟、回滚演练） |

发布门禁：候选必须签名、包含 SBOM 与 7 类证据，经 admin 审批后才能发布。
参见 [运维手册](../docs/04-operations/runbooks.md)、
[开发者指南](../docs/05-product/developer-guide.md) 与
[发布说明 v1.0.0 GA](../docs/05-product/release-notes/v1.0.0.md)。

## Windows 安装器（已构建）

- 产物：`installers/windows/GodotAIAgent-Setup-1.0.0.exe`（约 35 MB）
- SHA-256：`7D9CC3E319B609EDEAAA7B6DA125C774727557904F913A042A6E4C879399D370`
- 内含：E12 后端 `godot-ai-backend.exe`（PyInstaller onefile，含 product 模块与全部 33 个迁移）、
  `Start-Backend.cmd` 启动脚本、Godot 插件、用户/开发/运维文档。
- 默认安装到用户目录（`%LOCALAPPDATA%\Programs\GodotAIAgent`），无需管理员；
  数据目录 `%LOCALAPPDATA%\GodotAIAgent` 与安装目录分离，卸载保留用户数据。
- 启动脚本自动设置 `GODOT_AI_DATABASE_URL` 等，开箱即用；已验证安装后
  `Start-Backend.cmd --migrate` 可将数据库升级到 head `000033`。

重建步骤：

```powershell
# 1. 构建后端 exe（apps/backend 下）
cd apps/backend
.\.venv\Scripts\python.exe -m PyInstaller godot-ai-backend.spec --noconfirm `
  --distpath ..\..\artifacts\dist-e12 --workpath ..\..\artifacts\build-e12

# 2. 编译安装器（仓库根目录；ISCC 以便携模式置于 .tools/innosetup）
.tools\innosetup\ISCC.exe scripts\release\installer-windows.iss
```

构建脚本：[installer-windows.iss](../scripts/release/installer-windows.iss)、
[godot-ai-backend.spec](../apps/backend/godot-ai-backend.spec)、
[Start-Backend.cmd](../scripts/release/packaging/Start-Backend.cmd)。
