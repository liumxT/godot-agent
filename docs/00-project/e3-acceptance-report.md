# E3 验收报告

- **阶段：** E3 Godot Integration
- **日期：** 2026-11-20
- **设计依据：** [E3 设计与任务拆解](../02-architecture/e3-godot-integration-design.md)
- **任务计划：** [E3 开发计划](../../完整开发计划细分/E3.md)
- **结论：** ✅ 通过验收，可进入 E4

## 1. 范围与批次

| 批次 | 任务 | 状态 |
| --- | --- | --- |
| E3-M1 | T01 插件生命周期、T02 服务管理 | ✅ |
| E3-M2 | T03 Backend Discovery、T04 Bridge 协议、T05 WebSocket Client | ✅ |
| E3-M3 | T06 认证、T07 Session、T08 Lease、T17 连接 UI | ✅ |
| E3-M4 | T09 心跳、T10 事件同步、T11 快照 | ✅ |
| E3-M5 | T12 重连恢复、T13 多 Editor 隔离、T14 项目身份 | ✅ |
| E3-M6 | T15 状态采集、T16 Runtime Bridge、T18 集成测试与收尾 | ✅ |

## 2. 交付物核对

| 编号 | 交付物 | 位置 | 状态 |
| --- | --- | --- | --- |
| E3-D01 | Plugin Lifecycle | `apps/godot-plugin/addons/godot_ai_agent/core/plugin_lifecycle.gd` | ✅ |
| E3-D02 | Plugin Service Registry | `core/service_registry.gd`、`core/service.gd`、`core/plugin_context.gd` | ✅ |
| E3-D03 | Backend Discovery | `services/backend_discovery_service.gd` | ✅ |
| E3-D04 | Editor Bridge Protocol | `packages/contracts/bridge/`（7 个 schema）、`bridge/protocol_adapter.gd` | ✅ |
| E3-D05 | WebSocket Client | `bridge/editor_bridge_client.gd`、`bridge/connection_state.gd` | ✅ |
| E3-D06 | Editor Authentication | `services/editor_auth_service.gd`、`apps/backend/src/app/ws/editor.py` | ✅ |
| E3-D07 | Editor Session Manager | `modules/editor_session/`、`services/editor_session_service.gd` | ✅ |
| E3-D08 | Session Lease Manager | `modules/lease/`、迁移 `000007` | ✅ |
| E3-D09 | Heartbeat Manager | `services/heartbeat_service.gd` | ✅ |
| E3-D10 | Event Sync | `services/event_sync_service.gd`、`modules/bridge_event/` | ✅ |
| E3-D11 | Snapshot Service | `services/snapshot_service.gd`、`modules/snapshot/` | ✅ |
| E3-D12 | Reconnection & Recovery | `services/reconnection_service.gd` | ✅ |
| E3-D13 | Multi-Editor Support | `editor_session` 绑定/查询、`/bridge/sessions` | ✅ |
| E3-D14 | Project Identity Provider | `state/project_identity.gd`、`modules/project/` | ✅ |
| E3-D15 | Editor State Provider | `state/editor_state_provider.gd` | ✅ |
| E3-D16 | Runtime Bridge | `runtime/runtime_bridge.gd`、`app/ws/runtime.py`、`modules/runtime/`、迁移 `000009` | ✅ |
| E3-D17 | Editor Connection UI | `ui/connection_panel.gd`、`ui/status_panel.gd` | ✅ |
| E3-D18 | E3 Integration Test Suite | `apps/backend/tests/{unit,integration}/test_e3_*.py`、`apps/godot-plugin/tests/e3/`、`check_all.py` | ✅ |
| E3-D19 | E3 Acceptance Report | 本文件 | ✅ |

## 3. 验证证据

| 项 | 结果 |
| --- | --- |
| 后端单元 + 集成测试 | 319 passed |
| 后端契约测试 | 42 passed |
| 后端合计 | **361 passed**（`pytest -q`） |
| Godot 侧测试 | **68/68 passed**（编辑器 headless 入口 `-- --e3-test`） |
| 静态检查 | `ruff format --check` / `ruff check` 全通过（179 files formatted） |
| 全量检查 | `check_all.py` **8 阶段全 PASS**：仓库结构、敏感文件、代码格式、静态检查、Contracts Schema、Backend 测试、Godot Plugin、Godot Bridge Tests |
| 数据库迁移 | head 为 `000009`；一次升级、重复幂等、checksum 篡改检测均通过 |
| Runtime 集成 | `tests/integration/test_e3_runtime.py` 5 passed（注册、停止、越权、未登记指纹、过期清理） |
| Fencing 回归 | `test_stale_fencing_token_is_rejected`（E3-IT-013）通过 |

执行命令：

```powershell
# 后端
cd apps/backend
.\.venv\Scripts\python.exe -m ruff check src tests migrations
.\.venv\Scripts\python.exe -m ruff format --check src tests migrations
.\.venv\Scripts\python.exe -m pytest -q

# Godot 侧
& $env:GODOT_BIN --headless --path apps/godot-plugin --editor --quit-after 1200 -- --e3-test

# 全量
$env:GODOT_BIN='...\Godot_v4.5.1-stable_win64_console.exe'
.\.venv\Scripts\python.exe ..\..\scripts\testing\check_all.py
```

## 4. DoD 核对

| 完成定义 | 状态 | 证据 |
| --- | --- | --- |
| Godot Plugin 生命周期稳定 | ✅ | `test_plugin_lifecycle.gd`、`test_service_registry.gd` |
| Plugin 内部服务管理正常 | ✅ | `core/service_registry.gd` + T02 用例 |
| Backend Discovery 正常 | ✅ | `test_backend_discovery.gd`（五种状态、退避） |
| Editor Bridge Protocol 定义完成 | ✅ | `packages/contracts/bridge/`、`test_protocol_adapter.gd` |
| WebSocket 双向通信正常 | ✅ | `test_editor_bridge_client.gd`、`test_e3_editor_bridge.py` |
| Editor Authentication 正常 | ✅ | `test_editor_auth_service.gd`、`test_e3_editor_bridge.py` |
| Editor Session 正常 | ✅ | `test_editor_session_service.gd`、`modules/editor_session/` |
| Session Lease 正常 | ✅ | `modules/lease/`、`test_e3_bridge_recovery.py` |
| Heartbeat 正常 | ✅ | `test_heartbeat_service.gd`、`test_e3_editor_bridge.py` |
| Event Sync 正常 | ✅ | `test_event_sync_service.gd`、`test_e3_bridge_event.py` |
| Snapshot 机制正常 | ✅ | `test_snapshot_service.gd`、`test_e3_snapshot.py` |
| 断线重连和恢复正常 | ✅ | `test_reconnection_service.gd`、`test_e3_bridge_recovery.py` |
| 多 Editor 同时连接测试通过 | ✅ | `test_e3_editor_bridge.py`（多 Session/Lease 隔离） |
| 多项目隔离测试通过 | ✅ | `test_e3_editor_bridge.py`、`test_e3_runtime.py`（跨项目拒绝） |
| Editor State Provider 正常 | ✅ | `test_editor_state_provider.gd`（采集、diff、节流） |
| Runtime Bridge 基础测试通过 | ✅ | `test_runtime_bridge.gd`、`test_e3_runtime.py` |
| 未保存资源状态能够识别 | ✅ | `test_editor_state_provider.gd`（未保存资源与快照复用） |
| 旧 Lease 和旧 Fencing Token 无法执行受保护操作 | ✅ | `test_stale_fencing_token_is_rejected`、Lease 校验用例 |
| 安全测试通过 | ✅ | 见第 5 节 E3-SEC-001…010 |
| P0 自动化测试全部通过 | ✅ | 361 passed + 68/68 |
| 真实 Godot Editor 集成测试通过 | ✅ | headless 编辑器入口 + `check_all` Godot 两阶段 |
| 代码审查完成 | ✅ | 批次自检 + ruff + 契约 + 全量检查 |
| 阶段验收报告完成 | ✅ | 本文件 |

## 5. 安全测试

| 编号 | 要求 | 证据 |
| --- | --- | --- |
| E3-SEC-001 | Editor Bridge 必须经过身份认证 | 握手强制 HELLO → AUTH_CHALLENGE → AUTH_RESPONSE，未认证不建 Session |
| E3-SEC-002 | Runtime Bridge 使用独立认证 | `/api/v1/ws/runtime` 独立端点与独立凭证，`test_e3_runtime.py` |
| E3-SEC-003 | Session 不能由客户端自行伪造 | Session 仅由后端在认证成功后签发，插件只接收 `SESSION_CREATED` |
| E3-SEC-004 | Lease 过期后拒绝受保护操作 | `LeaseService.validate` 状态与到期校验 |
| E3-SEC-005 | Fencing Token 必须经过 Backend 验证 | 旧 token 抛 `FENCING_TOKEN_STALE`（E3-IT-013） |
| E3-SEC-006 | 不同项目不能共享未授权状态 | 项目指纹匹配 + 跨项目注册拒绝 |
| E3-SEC-007 | 连接断开后停止新的受保护操作 | 断连撤销租约，恢复前 `RECOVERING` 绑定 |
| E3-SEC-008 | 未保存资源状态必须被明确识别 | `unsaved_resources` 为快照必填字段，采集失败安全回退 |
| E3-SEC-009 | Backend 不能把缓存状态当作实时 Editor 状态 | `editor.state.report` 只返回 accepted/changed，不落库 |
| E3-SEC-010 | Runtime 不能继承 Editor 写入权限 | Runtime 端点仅允许 `bridge.runtime.report`，其余返回 `PERMISSION_DENIED` |

## 6. 设计确认项处置

| 编号 | 决策 | 落地 |
| --- | --- | --- |
| E3-Q1 | 不另建 Bridge Envelope，业务帧复用 1.0 | 控制帧新增 `RUNTIME_REGISTERED`，请求/响应沿用 1.0 |
| E3-Q2 | 双端点 `/ws/editor` 与 `/ws/runtime` | `app/ws/editor.py`、`app/ws/runtime.py` |
| E3-Q3 | Editor 凭证存放用户目录 | `user://godot_ai_agent/credentials.json`，不进项目 |
| E3-Q4 | Session/Lease 在握手内完成 | `SESSION_CREATED` 一次返回，插件不接触 Token |
| E3-Q5 | `SUSPENDED` 落在绑定状态 | `e3_editor_sessions.binding_status` |
| E3-Q6 | 项目 ID = `prj_` + 路径摘要 | `modules/project/service.py` |
| E3-Q7 | E3 不阻塞未授权项目连接 | 仅展示，受保护写操作留给 E5+ |
| E3-Q8 | 同项目多 Editor 允许并存 | 项目级 fencing token 唯一化写入 |
| E3-Q9 | Runtime 由用户显式启用 autoload | 插件菜单 `启用/禁用运行时探针` |
| E3-Q10 | 自建 headless 测试运行器 | `tests/test_runner.gd` + `tests/e3_runner/` |
| E3-Q11 | 心跳/租约参数配置化 | `bridge_*` settings，Runtime 默认 5s |
| E3-Q12 | 仅 PERSISTENT 事件入库 | 状态上报与运行状态使用 EPHEMERAL |

## 7. 已知限制与后续

| 事项 | 影响 | 计划 |
| --- | --- | --- |
| `editor_status=BUSY` 无法从 Godot API 判定 | 忙碌状态只上报 READY/UNKNOWN | 后续按 Editor 运行态扩展 |
| Runtime 凭证需单独签发（`client_type=tool`） | 未配置时 Runtime 探针保持 DISABLED | E4 客户端管理界面统一签发 |
| Runtime 指纹依赖规范化绝对路径 | 符号链接路径可能与 Editor 登记不一致 | 需要时改用 realpath 解析 |
| Runtime 探针无离线队列 | 断网期间状态不补发 | 仅为状态探针，不承载业务事件 |
| `check_all` Godot 阶段依赖可写的 Godot 用户目录 | 受限环境需放行 `%APPDATA%/Godot` | CI 中使用独立用户目录 |

## 8. 验收结论

E3 全部 6 个批次、18 个任务完成，DoD 23 项全部满足；后端 361 passed，
Godot 侧 68/68 passed，`check_all.py` 8 阶段全 PASS，安全要求 E3-SEC-001…010 均有对应测试或实现证据。
**同意 E3 通过验收，可进入 E4。**
