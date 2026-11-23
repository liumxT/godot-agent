# E5 验收报告：AI & Tool Foundation

**阶段：** E5  
**文档版本：** V1.0  
**验收日期：** 2026-11-23  
**迁移版本：** `000015`  
**结论：** 通过（P0 范围全部完成；已知限制见第 6 节）

---

## 1. 交付范围

| 任务 | 内容 | 状态 | 主要实现 |
|---|---|---|---|
| T01–T04 | Model Gateway 域模型、Provider 接口/适配器、Provider 配置 | 完成 | `modules/model_gateway/{models,registry,configuration}.py`、`providers/*` |
| T05–T07 | Model Registry、Capability Registry、Model Routing | 完成 | `registry.py`、`routing.py`；UNKNOWN 不视为 SUPPORTED |
| T08–T10 | 统一请求/响应、流式响应 | 完成 | `schemas.py`、`gateway.py` |
| T11–T13 | Token、Cost、调用审计 | 完成 | `gateway.py`、`cost.py`、`000012` 迁移 |
| T14 | 重试与超时 | 完成 | `gateway.py`；TIMEOUT/NETWORK_ERROR/UNKNOWN_RESULT 不重复发送 |
| T15–T16 | Prompt 版本化、Context Assembly | 完成 | `prompt.py`、`context.py`、`000013` 迁移 |
| T17–T21 | Tool Registry、Schema、权限、风险、审批 | 完成 | `modules/tool/{registry,permissions,risk,approval}.py`、`000014` 迁移 |
| T22–T27 | 执行引擎、幂等、资源锁、审计、验证、恢复 | 完成 | `execution.py`、`idempotency.py`、`locks.py`、`audit.py`、`verification.py`、`recovery.py`、`000015` 迁移 |
| T28 | Godot Tool Adapter | 完成 | `godot_adapter.py`、`modules/editor_command/hub.py`、插件 `tool_command_service.gd` |
| T29 | File Tool Adapter | 完成 | `file_adapter.py`（11 个 `file.*` 工具） |
| T30 | Tool API & UI | 完成 | `app/api/{tools,models}.py`、管理页区块、`cancel` |
| T31 | 集成 / 安全 / 故障恢复测试 | 完成 | `test_e5_acceptance.py` 等（见第 3 节） |

## 2. 架构边界

- Model Gateway 与 Tool System 互不依赖，均由 E6 Agent Runtime 通过统一接口调用。
- 所有项目操作（文件、场景、节点、Inspector、信号、组、运行时）必须经过 Tool System。
- 编辑器工具只经 Editor Plugin 的真实 Editor API 执行，禁止改写 `.tscn` 文本冒充。
- 工具定义按版本不可变；执行记录、审计与验证只追加或按状态机迁移。

## 3. 验收场景与证据

### 场景 A：AI 模型调用

- Provider 配置、模型路由、统一响应、Token/Cost/审计落库。
- 证据：`tests/integration/test_e5_model_gateway.py`、
  `test_e5_model_invocation.py`、`tests/unit/test_e5_model_io.py`、
  `test_e5_providers.py`、`test_e5_prompt_context.py`。
- 关键断言：能力 UNKNOWN 不放行、缺价格记 UNAVAILABLE、流式事件顺序、
  超时/网络错误不重发非幂等请求。

### 场景 B：只读工具执行

- 通过内置 `file.read` 完成：工具解析 → 权限（viewer/project.read）→ 资源锁 →
  File Adapter 路径安全 → 读取 → 验证 VERIFIED → 审计可查询。
- 证据：`tests/integration/test_e5_acceptance.py::test_read_only_tool_runs_end_to_end`。

### 场景 C：写工具治理

- `file.write`（R2）在无 ChangeSet 时被拒绝（`CHANGESET_REQUIRED`），磁盘无副作用；
  写路径另由 `test_e5_tool_execution.py` 覆盖锁冲突、幂等复用、审批与审计。
- 证据：`test_e5_acceptance.py::test_project_write_requires_changeset_and_does_not_touch_disk`。

### 场景 D：故障与恢复

- 编辑器命令超时 → 执行状态 UNKNOWN；恢复流程通过 Adapter `inspect` 观测后转 SUCCEEDED，
  验证记录 VERIFIED；无法确认时保持 UNKNOWN，不宣布成功。
- 证据：`test_e5_acceptance.py::test_unknown_execution_recovers_after_editor_reconnect`、
  `test_e5_tool_adapters.py`（超时 → UNKNOWN、断连 → EDITOR_NOT_CONNECTED）。

## 4. 安全要求核对

| 要求 | 结论 | 证据 |
|---|---|---|
| Provider API Key 不明文落库、日志不输出完整 Key | 通过 | `configuration.py` 使用 SecretStore；响应仅返回 `credential_ref` |
| 路径不得逃逸项目根目录 | 通过 | `file_adapter.py` 拒绝 `..`、绝对路径、符号链接逃逸、隐藏路径、敏感文件 |
| 工具权限与项目访问级别一致 | 通过 | `permissions.py`；写工具需 `project.write` 与非空 resource scope |
| 高风险工具需审批 | 通过 | R3/R4 接入 E4 审批；R2 需 ChangeSet |
| 执行可追溯 | 通过 | `tool_executions`、`tool_audit_records`、`tool_verification_results` |
| 取消不产生"假成功" | 通过 | EXECUTING 禁止取消；取消后状态 CANCELLED 并写审计 |

## 5. 质量门禁

| 项目 | 结果 |
|---|---|
| 后端 pytest | 481 passed（unit + integration / contract） |
| 后端 ruff | 全部通过（line-length 100） |
| Godot 插件测试 | 68/68 passed（headless） |
| 共享契约探针 | 38/38 passed |
| Alembic head | `000015` |

## 6. 已知限制

1. `godot.debug.*` 无可靠 Editor API，返回 `TOOL_UNSUPPORTED`，不伪造调试输出。
2. Animation/TileMap 工具覆盖常用读写；复杂资源（自定义轨道、替代图块）未全部覆盖。
3. File 写入后的资源导入由编辑器完成，验证记录为 `import_pending = None`，
   执行验证状态可能为 PARTIAL；系统不生成也不猜测 UID。
4. 管理页为内置 HTML 简易视图，仅覆盖项目、任务、审批、工具、执行与模型汇总。
5. E5 §20 的扩展表（`tool_execution_attempts` 等）未创建；现有四表满足 T22–T27 语义。
6. 工具取消仅支持未分发状态；已分发命令依赖编辑器应答或恢复流程。

## 7. 结论与后续

E5 P0 目标（E5-G01–G20）均已落地并有自动化证据支撑，可以进入 E6 Agent Runtime。
E6 通过 `ModelGatewayService` 与 `ToolExecutionService` 的统一接口组合 Agent Loop，
不应绕过 Tool System 直接操作项目。
