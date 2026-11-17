# CI 与自动化检查（E0-T09）

## 1. 方案

| 项 | 决策 |
| --- | --- |
| CI 平台 | GitHub Actions（[.github/workflows/ci.yml](../../.github/workflows/ci.yml)） |
| 本地同源检查 | [scripts/testing/check_all.py](../../scripts/testing/check_all.py) |
| 检查报告 | `artifacts/ci-report.md` + `artifacts/ci-report.json`（不入库） |

仓库尚无 remote，当前以本地脚本为权威检查；推送至 GitHub 后
workflow 自动生效，二者执行同一套规则，避免"本地过、CI 挂"。

## 2. 检查阶段

| 顺序 | 阶段 | 内容 | 失败即阻断 |
| --- | --- | --- | --- |
| 1 | 仓库结构 | 必需目录与文件齐全 | 是 |
| 2 | 敏感文件 | `.env`、密钥文件、私钥/云凭证特征 | 是 |
| 3 | 代码格式 | `ruff format --check` | 是 |
| 4 | 静态检查 | `ruff check` | 是 |
| 5 | Contracts Schema | `pytest tests/contract` | 是 |
| 6 | Backend 测试 | `pytest --ignore=tests/contract` | 是 |
| 7 | Godot Plugin | `--headless --editor` 加载 + 契约探针 | 是 |

Godot 阶段找不到可执行文件时记为 `SKIP`（本地未安装时不阻塞），
GitHub Actions 的 `godot` job 会下载 Godot 4.5.1 并强制执行。

## 3. 本地运行

在 Backend 虚拟环境中执行（脚本依赖 pytest / ruff 所在解释器）：

```powershell
cd apps/backend
$env:GODOT_BIN = 'D:\应用程序\godot\Godot_v4.5.1-stable_win64.exe\Godot_v4.5.1-stable_win64_console.exe'
.\.venv\Scripts\python.exe ..\..\scripts\testing\check_all.py
```

退出码：`0` 全部通过或跳过；`1` 存在失败阶段。报告写入仓库根 `artifacts/`。

`GODOT_BIN` 未设置时依次查找 PATH 中的 `godot` / `godot4`。

## 4. GitHub Actions

`ci.yml` 包含两个 job：

| Job | 内容 |
| --- | --- |
| `backend` | 安装 `apps/backend[dev]`，运行 `check_all.py`，上传 `artifacts/` |
| `godot` | 下载 Godot 4.5.1 linux 版，加载插件 + 运行契约探针 |

触发：`push`（main / develop / feature / bugfix / hotfix）与 `pull_request`。

## 5. 合并保护（推送后配置）

在 GitHub 仓库设置中：

1. 保护 `main` 与 `develop`，禁止直接 push。
2. 要求 `Backend checks` 与 `Godot plugin checks` 通过后才可合并。
3. 要求至少 1 人 review。

## 6. 失败处理

1. 报告与 job 日志保留失败阶段的原始输出（截取末 2000 字符）。
2. 本地复现：单独运行失败阶段对应命令（见上表）。
3. 不允许通过跳过检查（`-k`、注释 workflow）来合并。
4. 环境类失败（下载 Godot、网络）需重跑或在 Issue 记录后再合并。

## 7. 后续扩展

E1–E12 在 `check_all.py` 中追加阶段（数据库迁移、API 契约、
Editor Bridge、Agent Runtime、资源导入、导出与发布），
不改变现有阶段顺序。

## 8. 验收

```powershell
cd apps/backend
.\.venv\Scripts\python.exe ..\..\scripts\testing\check_all.py; echo "exit=$LASTEXITCODE"
```

期望：7 个阶段全部 `PASS`（未装 Godot 时 Godot 阶段为 `SKIP`），
退出码 `0`，`artifacts/ci-report.md` 生成。
