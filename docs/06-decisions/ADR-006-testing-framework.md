# ADR-006：测试框架与验证策略

- **状态：** Accepted
- **决策日期：** 2026-11-17
- **决策人：** 项目负责人
- **相关文档：** [ADR-002](ADR-002-backend-framework.md)、[E0-T09](../../完整开发计划细分/E0.md)、[E0 测试报告](../00-project/e0-test-report.md)、[CI 规范](../03-development/ci.md)

## 1. 背景与问题

项目同时包含 Python Backend 与 GDScript 插件，测试需要覆盖：

- 单元逻辑（配置、错误、日志、迁移）。
- 集成链路（lifespan、SQLite、HTTP 接口）。
- 跨进程契约（同一批 Schema 样例在两端都能验证）。
- 编辑器插件加载与生命周期。
- 故障注入（配置缺失、迁移失败、目录不可用）。

需要在本地一条命令执行，并在 CI 中稳定复现。

## 2. 比较标准

| 标准 | 说明 |
| --- | --- |
| 覆盖能力 | 异步、HTTP、Schema、进程级检查 |
| 执行速度 | 提交前可全量运行 |
| 依赖体积 | 不引入重型测试平台 |
| 输出可解析 | CI 能判定通过/失败并留存报告 |
| 双语言适配 | Python 与 GDScript 各有可靠验证方式 |
| 可维护性 | 测试目录结构与模块边界一致 |

## 3. 备选方案

| 方案 | 评价 |
| --- | --- |
| **pytest + pytest-asyncio + httpx + jsonschema** | 生态成熟、异步支持好、ASGI 直连、Schema 校验直接可用 |
| unittest | 标准库但异步与夹具能力弱，输出扩展性差 |
| Robot Framework | 面向验收关键字，开发期单测成本高 |
| GUT / GdUnit4（Godot） | GDScript 单测框架；E0 只需插件加载与契约验证，暂不引入 |
| 仅手工验证 | 无法在 CI 中阻断回归，违反验收要求 |

## 4. 决策

| 层 | 选型 |
| --- | --- |
| Backend 单测/集成 | pytest，`asyncio_mode=auto`，`pythonpath=src` |
| HTTP 集成 | httpx `ASGITransport`（无端口）+ `TestClient`（生命周期） |
| 契约校验 | `jsonschema`（Draft 2020-12）+ `packages/contracts/schemas/manifest.json` |
| 代码质量 | ruff（format + check），作为 CI 门禁 |
| Godot 验证 | headless 编辑器模式加载插件 + 独立 `contract_probe` 测试插件 |
| 进程级验证 | 检查退出码与结构化日志（`[GodotAI] {json}`） |
| 故障注入 | 以 `pytest.raises` 显式覆盖失败路径 |
| 编排 | `scripts/testing/check_all.py`（本地与 CI 同一脚本） |

附加约束：

1. 不使用 Mock 替代完整链路（数据库、Schema、编辑器加载必须真实执行）。
2. 测试中的数据库必须位于 `tmp_path`，不得触碰用户数据目录。
3. 测试必须传 `_env_file=None`，避免本机 `.env` 影响结果。
4. 涉及 Secrets 的测试只使用内存实现，不写入系统凭证库。
5. 新增功能必须同时提供测试，否则 Code Review 阻塞。

## 5. 选择理由

1. pytest 的夹具与参数化能力适合覆盖配置矩阵与 Schema 正反例。
2. httpx ASGI 直连让集成测试无需占用端口，CI 更稳定。
3. 契约样例由 manifest 驱动，Backend 与 Godot 读取同一份数据，避免协议漂移。
4. Godot 没有引入单测框架，是因为 E0 的插件逻辑极少；用 headless + 探针即可获得
   进程级真实证据，成本更低。

## 6. 影响范围

| 影响项 | 说明 |
| --- | --- |
| E0-T03 | `tests/unit`、`tests/contract`、`tests/integration` 目录结构 |
| E0-T05 | 契约样例由 manifest 组织，两端共用 |
| E0-T09 | CI 阶段划分按测试类型拆分为独立阶段 |
| E3+ | 插件逻辑增长后需评估引入 GDScript 单测框架 |

## 7. 变更条件

- 插件内出现需要细粒度单测的复杂逻辑（如 `.tscn` 解析），届时引入 GUT/GdUnit4，
  并与 headless 探针并存。
- 测试全量执行时间超过可接受阈值（例如 > 2 分钟），需拆分快速/完整两档。
- 需要在真实端口验证 WebSocket 行为时，增加独立集成任务而非替换现有方式。

## 8. 尚未冻结的细节

性能测试方案（E9）、端到端 GUI 自动化（E9/E10）、覆盖率门禁阈值（E1 起评估）。
