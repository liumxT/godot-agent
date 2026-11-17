# ADR-002：Backend 框架与基础库

- **状态：** Accepted
- **决策日期：** 2026-11-17
- **决策人：** 项目负责人
- **相关文档：** [ADR-001](ADR-001-backend-language.md)、[E0-T02](../../完整开发计划细分/E0.md)、[实施蓝图 §2/§8](../../实施蓝图.md)

## 1. 背景与问题

在 Python 已确定的前提下，需要确定 HTTP/WebSocket 服务框架、契约校验、ORM 与迁移、
测试栈，使 E0 骨架与 E1/E2 的模块实现基于同一套基础库。

## 2. 比较标准

| 标准 | 说明 |
| --- | --- |
| 原生异步 + WebSocket | 插件与后端长连接、双向消息 |
| 契约校验能力 | Envelope、Event、Command 均需强校验 |
| 与 SQLite 的适配 | 单文件库、WAL、迁移可控 |
| 生态成熟度 | 文档、招聘、社区问题可查 |
| 依赖体积 | 影响打包产物大小 |
| 生命周期管理 | 启动装配、优雅关闭、后台 Worker |

## 3. 备选方案

| 方案 | 评价 |
| --- | --- |
| **FastAPI + uvicorn** | 原生 async、WebSocket 一等支持、Pydantic 深度集成、OpenAPI 自动生成 |
| Litestar | 性能与类型支持好，生态与资料明显少于 FastAPI |
| Flask | 同步模型为主，WebSocket 需额外扩展，不适合 Agent 长任务 |
| Django + Channels | 重量级，ORM 与模块化单体边界冲突，启动成本高 |

ORM/迁移备选：SQLAlchemy 2.0 + Alembic（选）、裸 sqlite3（手工迁移，不可控）、
Peewee（迁移能力弱）、Prisma Python（生态不成熟）。

## 4. 决策

| 关注点 | 选型 |
| --- | --- |
| HTTP/WebSocket 服务 | FastAPI + uvicorn |
| 数据校验 | Pydantic v2（同时导出 JSON Schema 作为 Contract 事实源） |
| ORM | SQLAlchemy 2.0（async 引擎，驱动 aiosqlite） |
| 迁移 | Alembic（迁移文件入仓，禁止运行时自动建表） |
| 数据库 | SQLite，WAL + `busy_timeout` + 短事务 |
| 测试 | pytest + pytest-asyncio + httpx（ASGI 直连） |
| 日志 | 标准库 logging + JSON formatter，统一 request/task 关联 ID |
| 配置 | 环境变量 + `.env.example`，密钥不入仓、不入项目目录 |
| 打包 | PyInstaller（备选 Nuitka） |

附加约束：

1. 服务仅绑定 `127.0.0.1`，不监听 `0.0.0.0`。
2. WebSocket 与 HTTP 共享同一认证基座（本地 token + 会话租约），细节由 E2 定义。
3. 一个 SQLite 主库、单写者；跨模块事务通过 Outbox 实现最终一致（蓝图 §8.4）。
4. 模块不得直接使用其他模块的 Repository（蓝图 §2.3）。
5. 框架层不得承载业务逻辑，入口只做装配与路由。

## 5. 选择理由

1. FastAPI 的 WebSocket、async、Pydantic 校验三件事正好覆盖插件通信与契约校验需求，避免自建协议层。
2. Pydantic v2 可以同时产出运行时校验与 JSON Schema，使 Python 侧与 GDScript 侧的契约只有一个事实源。
3. SQLAlchemy 2.0 + Alembic 提供可审计的迁移历史，符合"数据库规范必须入仓"的要求。
4. httpx + ASGI 直连可在无真实端口的情况下完成集成测试，降低 CI 复杂度。

## 6. 影响范围

| 影响项 | 说明 |
| --- | --- |
| E0-T03 | Backend 骨架按 FastAPI 应用工厂 + 生命周期装配实现 |
| E0-T06 | 迁移目录、命名、版本表由 Alembic 管理 |
| E0-T05 | Contract 由 Pydantic 模型导出 JSON Schema |
| 打包 | Pydantic/SQLAlchemy 会增加产物体积，需在打包 spike 中度量 |
| 测试 | 默认 ASGI 直连，仅在协议真实性要求下启动真实端口 |

## 7. 变更条件

- FastAPI 的 WebSocket 能力无法满足双向流控或背压要求。
- SQLite 单写者在真实负载下出现不可接受的写阻塞（届时先评估 WAL 调优，再评估换库）。

## 8. 尚未冻结的细节

以下不属于本 ADR，留给对应阶段：默认端口号、token 存储位置与轮换策略（E2）、
Outbox 表结构与投递语义（E1/E4）、日志字段集（E0-T08）。
