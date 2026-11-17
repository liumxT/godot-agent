# ADR-001：Backend 编程语言

- **状态：** Accepted
- **决策日期：** 2026-11-17
- **决策人：** 项目负责人
- **相关文档：** [E0-T02](../../完整开发计划细分/E0.md)、[实施蓝图 §2/§12](../../实施蓝图.md)、[ADR-002](ADR-002-backend-framework.md)

## 1. 背景与问题

平台需要一个 Local Backend 承载：模块化单体、SQLite 持久化、认证 WebSocket、
Model Gateway、Tool System、Agent Runtime、多 Agent 编排、资产管线、验证与构建调度。
需要确定唯一的实现语言，且该决策在 E6 之后返工成本极高，必须在 E0 冻结。

## 2. 比较标准

| 标准 | 权重依据 |
| --- | --- |
| AI/Provider SDK 生态 | E5–E8 全部模块依赖模型、图像、音频 Provider |
| 迭代速度 | E0–E12 共 13 个阶段，小团队交付 |
| 并发与长任务模型 | Agent 长任务、Worker、可恢复执行 |
| 类型与可维护性 | 模块边界、Contract 校验、长期演进 |
| 本地分发能力 | E12 需交付可安装的本地软件 |
| GDScript/.tscn 文本处理 | Project Intelligence 需要解析项目源码与资源 |
| 本机环境匹配度 | 减少环境准备成本 |

## 3. 备选方案

| 方案 | 优势 | 劣势 |
| --- | --- | --- |
| **Python + FastAPI** | AI SDK 覆盖最全、迭代最快、文本解析方便、本机已装 3.14.2 | 分发需打包、GIL 限制 CPU 并行、动态类型 |
| TypeScript + Node | 与 JSON 契约同构、异步模型好 | AI SDK 次优、类型口径与后端领域模型有摩擦 |
| C#/.NET | 类型最强、单文件/自包含分发最好 | AI SDK 生态最弱、领域代码量大、迭代慢 |
| Go | 单二进制、并发优秀 | AI 生态弱、领域建模冗长、迭代慢 |
| Rust | 性能与安全最优 | 开发速度不匹配 13 阶段交付 |

## 4. 决策

**Backend 统一使用 Python，基线版本 `3.14.2`（patch 级锁定，`requires-python = ">=3.14,<3.15"`）。

回退条件：E4 起任一必需依赖缺少 3.14 的官方支持或 wheel，降级到 3.13.x，并在
ADR-002 与 [打包 ADR](ADR-007-packaging.md) 中同步记录后重新验证。

附加约束：

1. 所有依赖通过 lockfile 锁定，禁止浮动版本。
2. 类型注解视为强制项：核心模块必须通过静态检查，不允许无注解的公共接口。
3. CPU 密集型任务（项目全量索引、代码解析）不得占用事件循环，必须走独立 Worker 进程。
4. Backend 不直接读写项目文件，必须经 Tool System（蓝图 §5.2 规则二）。
5. 不使用 Python 实现 Godot 插件逻辑，插件侧只用 GDScript。

## 5. 选择理由

1. E5–E8 的核心能力（模型网关、Agent 运行时、多 Agent、资产 Provider）全部属于 AI 生态密集型，Python 的 SDK 覆盖与迭代速度是决定性因素。
2. 打包分发的成本是一次性的、可验证的；而语言选错导致的领域层返工发生在 E6 之后，成本不可逆。
3. 项目的主要负载是 IO（Provider 调用、WebSocket、SQLite），GIL 不构成瓶颈；CPU 密集部分可隔离到 Worker。
4. 本机已具备 Python 3.14.2，无需额外环境准备。

## 6. 影响范围

| 影响项 | 说明 |
| --- | --- |
| 工程结构 | `apps/backend/` 采用 Python 包结构，模块边界不因语言调整 |
| 分发 | 需 PyInstaller/Nuitka 打包，产物预计 80–150MB |
| 性能 | 单写者 SQLite + 异步 IO；索引类任务走 Worker |
| 契约 | Contract 以 JSON Schema 为唯一事实源，语言中立 |
| 团队 | 需要 Python 工程规范（E0-T10） |

## 7. 验证门槛（E0-T02 内必须完成）

PyInstaller 打包 FastAPI + SQLite + WebSocket，在**未安装 Python 的目标机/干净用户环境**上启动成功并完成一次握手。
若该 spike 失败且 Nuitka 同样失败，则触发本 ADR 修订，评估切换 .NET 8 self-contained。

验证进展（2026-11-17）：已用 PyInstaller 6.22.3 构建 onedir/onefile 产物，验证启动、
数据库迁移与 `GET /health`，详见 [ADR-007](ADR-007-packaging.md)。"无 Python 的干净
机器"验证随 E10 安装包制作一并执行。

## 8. 变更条件

出现以下任一情况时重新评估：

- 打包方案在目标平台持续失败，且无法通过嵌入式解释器规避。
- 核心 Provider 缺少 Python SDK 且必须依赖官方原生库。
- 项目规模导致模块级静态检查与启动时间不可接受。
