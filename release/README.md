# 产品发布目录

本目录由 `scripts/release/build_product.py` 生成或组装，二进制产物不入库。

```powershell
python scripts/release/build_product.py --check
python scripts/release/build_product.py --output release
```

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
