# E3 Godot Integration 设计与任务拆解

- **状态：** DRAFT（待评审）
- **日期：** 2026-11-18
- **依据：** [E3.md](../../完整开发计划细分/E3.md)、[ADR-005 本地通信](../06-decisions/ADR-005-local-communication.md)、
  [ADR-003 Godot 版本](../06-decisions/ADR-003-godot-version.md)、[E1 设计](e1-backend-core-design.md)、
  [E2 设计](e2-backend-services-design.md)、[Shared Contracts](../../packages/contracts/README.md)
- **前置：** E0 / E1 / E2 已通过验收（[E2 验收报告](../00-project/e2-acceptance-report.md)）

## 1. 目标与边界

E3 建立 Godot Editor Plugin 与本地 Backend 之间的完整连接体系：发现、认证、会话、租约、心跳、
事件同步、快照恢复、多实例隔离、编辑器状态采集与 Runtime 独立通道。

| 编号 | 目标 | 完成标准 |
| --- | --- | --- |
| E3-G01 | Plugin 生命周期 | 启用、关闭、重复启用稳定，无残留服务与连接 |
| E3-G02 | Backend Discovery | 能区分未启动 / 启动中 / 正常 / 版本不兼容 / 不可达 |
| E3-G03 | Editor Bridge | WebSocket 双向请求、响应、事件与确认可用 |
| E3-G04 | 身份认证 | 复用 E2 挑战-响应认证，凭证不落项目 |
| E3-G05 | Editor Session | 每个 Editor 实例独立 Session，状态权威在 Backend |
| E3-G06 | Heartbeat | 在线判定与超时识别准确 |
| E3-G07 | Session Lease | 过期租约无法执行受保护操作 |
| E3-G08 | Event Sync | 事件编号、去重、确认与可丢弃更新分层 |
| E3-G09 | Snapshot Recovery | 断线后 Snapshot + 事件补齐可恢复状态 |
| E3-G10 | Multi-Editor | 多 Editor 并发连接互不污染 |
| E3-G11 | Project Isolation | 项目身份可识别，跨项目状态不共享 |
| E3-G12 | Editor State | 能采集第一阶段编辑器状态并标明未保存修改 |
| E3-G13 | Runtime Bridge | Runtime 独立认证与独立通道，不继承写权限 |
| E3-G14 | Integration Testing | 真实 Godot headless + 真实 uvicorn 集成测试通过 |

**非目标**（E5–E8 实现）：自动创建场景、Inspector / TileMap / 脚本修改工具集、Agent 执行循环、
多 Agent 协作、资源生成管线。E3 的受保护写操作只保留机制（Lease + Fencing），不提供具体写工具。

## 2. 现状与差距

| 能力 | 现状 | E3 需要补齐 |
| --- | --- | --- |
| 插件入口 | `plugin.gd` 仅版本校验 + 状态面板，无服务层 | 生命周期状态机、服务注册表、异常释放 |
| 插件目录 | `core/`、`bridge/`、`services/` 等为空目录 | 连接、协议、会话、心跳、事件、快照、状态采集 |
| 契约 | 已有 request / response / event / error / system / client / auth / session / project-access | 新增 bridge 控制帧、租约、会话绑定、快照、编辑器状态、Runtime 契约 |
| Backend API | `/api/v1` 全部为 HTTP，无 WebSocket | Editor/Runtime WebSocket 端点、会话绑定、租约、事件与快照服务 |
| Session | 仅 HTTP 创建/查询/撤销/续期，无 Editor 维度 | Editor 绑定、Lease、心跳、恢复 |
| 项目 | E2 只有 `project_access`，无项目注册表 | 项目身份识别与临时项目记录（E4 迁移为正式 Registry） |
| Runtime | 无任何代码 | 探针、独立认证、状态上报 |
| 测试 | `check_all` 仅 headless 加载插件与契约探针 | Godot 侧自动化测试运行器、WS 集成测试、故障注入 |

## 3. 架构与数据流

### 3.1 三端结构

```text
┌──────────────────────────── Godot Editor ────────────────────────────┐
│ plugin.gd (生命周期编排)                                              │
│   └─ PluginContext → ServiceRegistry                                 │
│        ├─ BackendDiscoveryService ── HTTP /health、/system/info       │
│        ├─ EditorBridgeClient ─────── WebSocket /api/v1/ws/editor      │
│        ├─ SessionService ─────────── 绑定/状态/续期/撤销              │
│        ├─ HeartbeatService ───────── 周期心跳 + 租约续期              │
│        ├─ EventSyncService ───────── 事件发布/接收/确认/去重          │
│        ├─ SnapshotService ────────── 快照生成/加载                    │
│        ├─ ReconnectionService ────── 退避重连 + 恢复编排              │
│        ├─ EditorStateProvider ────── 编辑器状态采集                   │
│        └─ ConnectionPanel (Dock) ─── 状态展示与用户操作               │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ WebSocket（仅 127.0.0.1）
┌───────────────────────────────▼──────────────────────────────────────┐
│ Local Backend                                                        │
│ app/ws/editor.py  →  BridgeSessionService → modules/{editor_session,  │
│                      lease, bridge_event, snapshot, project, runtime}│
│ 复用 E2：client 认证、Session、审计、限流、错误契约                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ WebSocket /api/v1/ws/runtime（独立凭证）
┌───────────────────────────────▼──────────────────────────────────────┐
│ Godot Game Runtime（runtime_bridge.gd autoload，用户显式启用）        │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 连接与恢复时序

```text
Plugin                          Backend
  │ WS connect ─────────────────▶│  建立连接，10s 内必须完成握手
  │◀────────────── AUTH_CHALLENGE │  challenge_id + nonce + server 信息
  │ HELLO（客户端/项目/版本）─────▶│  校验 protocol_version、项目身份
  │ AUTH_RESPONSE（HMAC proof）──▶│  E2 一次性挑战校验 + 失败限流/审计
  │◀────────────── SESSION_CREATED│  session + session_token + lease + 参数
  │ request session.heartbeat ───▶│  续租、更新 last_seen、返回 server_time
  │◀────────────────── event 推送 │  重要事件需 EVENT_ACK
  │ ... 断线 ...                  │
  │ 退避重连 → 重新 HELLO/AUTH ──▶│  Session 有效则复用，否则新建
  │ request editor.snapshot ─────▶│  取基准快照
  │ request bridge.events.since ─▶│  补齐缺失事件并校验 sequence
```

认证成功后插件只持有 `gds_` Session Token 与 Lease，不接触 `gda_` Access Token。

### 3.3 状态权威

| 状态 | 权威来源 | Backend 行为 |
| --- | --- | --- |
| Editor 当前状态 | Godot Editor | 只记录快照与事件，不推断实时状态 |
| Runtime 当前状态 | Godot Runtime | 只记录上报，不与 Editor 状态混用 |
| 磁盘持久化状态 | 文件系统 | 与未保存状态分开标注 |
| Session / Lease 状态 | Backend | 插件只缓存，不得自行延长或复活 |

### 3.4 线程与轮询模型

Godot 侧没有默认后台线程，`WebSocketPeer` 必须在每帧 `poll()`。设计为：

- `plugin.gd` 在 `_enter_tree()` 调用 `set_process(true)`，在 `_process(delta)` 中调用
  `ServiceRegistry.tick(delta)`。
- `EditorBridgeClient` 暴露 `poll()`，负责 `poll()`、连接状态迁移、收发队列；不直接接触 UI。
- 心跳/重连/超时全部由 `tick` 驱动的单调时钟计算，禁止使用阻塞等待（`OS.delay_msec` 只允许在测试脚本中）。
- headless 模式下 `_process` 同样运行，保证 CI 可验证。

## 4. 模块边界与目录规划

### 4.1 Godot 插件

```text
apps/godot-plugin/addons/godot_ai_agent/
├── plugin.cfg / plugin.gd           # 入口：生命周期编排，不含通信细节
├── core/
│   ├── plugin_lifecycle.gd          # 状态机 + 有序启动/关闭
│   ├── plugin_context.gd            # 配置、编辑器接口、日志、时钟
│   ├── service_registry.gd          # 注册、依赖排序、批量启动/停止
│   ├── service.gd                   # 服务契约基类
│   ├── logger.gd                    # 已有，扩展字段白名单与脱敏
│   └── contract_validator.gd        # 已有，扩展 bridge 契约校验
├── services/
│   ├── backend_discovery_service.gd
│   ├── session_service.gd
│   ├── heartbeat_service.gd
│   ├── event_sync_service.gd
│   ├── snapshot_service.gd
│   └── reconnection_service.gd
├── bridge/
│   ├── editor_bridge_client.gd
│   ├── protocol_adapter.gd
│   ├── action_registry.gd
│   └── connection_state.gd
├── state/
│   ├── editor_state_provider.gd
│   └── project_identity.gd
├── models/                          # 纯数据结构，不做 IO
│   ├── bridge_frame.gd
│   ├── lease.gd
│   └── editor_state.gd
├── ui/
│   ├── status_panel.gd              # 已有
│   └── connection_panel.gd
├── runtime/
│   └── runtime_bridge.gd            # 游戏进程侧 autoload
└── utilities/
    ├── backoff.gd
    └── credentials_store.gd
```

插件依赖规则（评审检查项，E3-ARC-001…006）：

1. `plugin.gd` 只依赖 `core/`，不直接引用 `services/`、`bridge/`、`ui/` 的具体实现。
2. `bridge/` 只负责帧收发与解析，不读写 Session、项目或 UI 状态。
3. `services/` 之间只通过 `PluginContext` 与信号交互，禁止互相持有具体实例。
4. `ui/` 只读取服务暴露的只读状态与信号，不发起网络调用。
5. `models/` 不依赖 `EditorInterface`、`WebSocketPeer`、`HTTPRequest`。
6. 任何 `@tool` 脚本不得在 `_exit_tree()` 之后继续持有 Editor 对象引用。

### 4.2 Backend

```text
apps/backend/src/
├── app/
│   ├── ws/
│   │   ├── editor.py                # /api/v1/ws/editor 端点与握手状态机
│   │   ├── runtime.py               # /api/v1/ws/runtime 端点
│   │   └── protocol.py              # 帧解析、大小限制、关闭码、错误映射
│   ├── api/
│   │   ├── bridge.py                # /bridge/status、/bridge/sessions（只读诊断）
│   │   └── diagnostics.py           # 扩展：诊断摘要新增 bridge 块
│   └── schemas/bridge.py            # 帧与 payload 的 Pydantic 模型
├── modules/
│   ├── project/                     # 临时项目身份（E4 迁移为 Registry）
│   ├── editor_session/              # Editor 绑定、连接状态
│   ├── lease/                       # 租约与 fencing token
│   ├── bridge_event/                # 事件持久化、sequence、确认
│   ├── snapshot/                    # 快照存取与保留
│   └── runtime/                     # Runtime 实例注册与状态
├── core/security/principal.py       # 新增 bridge.* Action
└── migrations/versions/000007_e3_editor_bridge.py
```

依赖规则：`app/ws` 只编排，不写 SQL；所有持久化经模块 Service；`modules/*` 不导入 `app/`；
WebSocket 端点必须在握手完成后才允许业务帧；所有受保护帧走 E2 授权依赖（按 Action）。

## 5. 关键设计

### 5.1 生命周期与服务注册（T01 / T02）

状态机（与 E1 生命周期风格一致，但作用于插件）：

```text
DISABLED → ENABLING → INITIALIZING → READY → DISABLING → DISABLED
                          │            │
                          └────────────┴──→ ERROR → DISABLING → DISABLED
```

- `plugin_lifecycle.gd` 维护状态与错误原因；`plugin.gd` 只做转发。
- 初始化顺序：读取配置 → 校验 Godot 版本 → 构建 `PluginContext` → 注册服务 →
  `start_all()`（Backend Discovery 优先）→ 注册 Dock → READY。
- 关闭顺序与启动逆序：停止心跳 → 停止事件同步 → 撤销 Lease → 关闭 Session（可选）→
  关闭 WS → 释放 Dock → 清空上下文。每步有超时，失败只记录不阻塞后续步骤。
- 重复启用：`_enabled` 与生命周期状态双重保护；`service_registry` 拒绝同名重复注册。
- 初始化失败：进入 ERROR，面板显示错误码，保留已创建资源的清理入口。

服务契约（`service.gd`）：

```text
initialize(context) -> bool
start() -> bool
tick(delta) -> void
stop(reason) -> void
status() -> Dictionary   # {state, error_code, detail}
dispose() -> void
```

`ServiceRegistry` 提供 `register(name, service, dependencies)`、`get(name)`、`start_all()`、
`stop_all(reason)`、`unregister(name)`、`tick(delta)`、`snapshot()`；启动按拓扑序，遇到失败标记依赖方为 BLOCKED。

### 5.2 Backend Discovery（T03）

- 地址来源优先级：`EditorSettings`（用户手动指定）→ 环境变量 `GODOT_AI_BACKEND_URL` →
  插件默认 `http://127.0.0.1:8765`。仅接受 `http://127.0.0.1` 或 `http://localhost`，其他主机直接判定为非法配置。
- 探测：`GET /api/v1/health/live`（存活）+ `GET /api/v1/system/info`（版本），单次超时 1.5s，总预算 3s。
- 结果分类：

| 结果 | 判定条件 | UI 提示 |
| --- | --- | --- |
| `BACKEND_NOT_STARTED` | 连接被拒绝 | 后端未启动，请启动后端 |
| `BACKEND_STARTING` | `/health/live` 失败但端口可连通 | 后端启动中，稍后重试 |
| `BACKEND_READY` | 健康 + `api_version == v1` | 已连接 |
| `BACKEND_INCOMPATIBLE` | `api_version` 或 `protocol_version` 不匹配 | 版本不兼容，需升级插件或后端 |
| `BACKEND_UNREACHABLE` | DNS/超时/网络错误 | 地址不可达 |
| `BACKEND_INVALID_URL` | 非回环或非法 URL | 只允许本机地址 |

- 失败重试：0.5s、1s、2s、4s、8s（上限 8s，带 ±20% 抖动），用户点击「连接」立即重置退避。
- 端口变化：监听探测失败后自动回到 Discovery，不在插件内扫描端口段。

### 5.3 Editor Bridge Protocol（T04）

**分层决策：** 不引入第二套业务 Envelope。业务消息直接复用 Shared Contracts 1.0 的
request / response / event / error；只有握手阶段的控制消息使用新增的
`packages/contracts/bridge/control.schema.json`。
这样 Godot 侧现有 `contract_validator.gd` 与 Backend 的契约测试可继续作为唯一事实源。

控制帧：

```json
{
  "protocol_version": "1.0",
  "message_id": "ctl_7f3a9c2e",
  "message_type": "HELLO",
  "timestamp": "2026-11-18T09:00:00Z",
  "session_id": null,
  "project_id": null,
  "correlation_id": null,
  "payload": {}
}
```

`message_type ∈ {HELLO, AUTH_CHALLENGE, AUTH_RESPONSE, SESSION_CREATED, RUNTIME_REGISTERED, ERROR}`，未知类型直接以 `ERROR` 关闭。
其中 `RUNTIME_REGISTERED` 仅由 Runtime 端点在认证成功后下发。

E3.md 消息类型到线上承载的映射：

| 逻辑类型 | 线上承载 |
| --- | --- |
| HELLO / AUTH_CHALLENGE / AUTH_RESPONSE / SESSION_CREATED / RUNTIME_REGISTERED | 控制帧 |
| HEARTBEAT | request，`action = session.heartbeat` |
| REQUEST / RESPONSE | request / response 契约 |
| EVENT | event 契约（`payload.sequence`、`payload.event_version`） |
| EVENT_ACK | request，`action = bridge.events.ack` |
| SNAPSHOT_REQUEST / SNAPSHOT_RESPONSE | request `editor.snapshot` / 对应 response（`data.kind = "snapshot"`） |
| ERROR | response（`success=false`）或控制帧 `message_type=ERROR` |

Action Registry（E3 落地，其余登记为 reserved）：

| Action | 方向 | 最小权限 | 说明 |
| --- | --- | --- | --- |
| `session.heartbeat` | plugin → backend | 有效 Session | 续租、更新 last_seen、返回 server_time |
| `editor.state.report` | plugin → backend | 有效 Session + Lease | 状态变更上报（轻量） |
| `bridge.events.publish` | plugin → backend | 有效 Session | 重要事件持久化 |
| `bridge.events.ack` | plugin → backend | 有效 Session | 确认已处理事件 |
| `bridge.events.since` | plugin → backend | 有效 Session | 恢复时按 sequence 拉取缺失事件 |
| `editor.snapshot` | 双向 | 有效 Session + Lease | 请求/返回快照 |
| `bridge.session.recover` | plugin → backend | 有效 Session | 恢复时校验绑定与租约 |
| `bridge.runtime.report` | runtime → backend | Runtime 凭证 | 运行状态/事件上报 |
| `editor.command.execute` | backend → plugin | reserved | E5 起使用，E3 返回 `NOT_IMPLEMENTED` |

协议规则：

1. `protocol_version` 必须匹配 `1.x`；主版本不一致返回 `PROTOCOL_VERSION_UNSUPPORTED` 并关闭连接。
2. 每个消息必须有唯一 ID；`response.request_id` 必须回填；未知 `request_id` 的 response 丢弃并计数。
3. 未登记的 `action` / 未登记字段 / 非法类型一律拒绝，不回显原始 payload。
4. 单帧上限 256 KiB；超限返回 `REQUEST_TOO_LARGE` 并关闭（关闭码 4409）。
5. 请求超时 15s（心跳 5s、快照 20s），超时后本地生成 `TIMEOUT` 响应。
6. 非幂等 action 未登记前不得重试；响应丢失一律标记 `UNKNOWN`。

新增契约文件（放 `packages/contracts/bridge/`，登记到 `packages/contracts/schemas/manifest.json`）：
`control.schema.json`、`session-created.schema.json`、`lease.schema.json`、`session-binding.schema.json`、
`editor-state.schema.json`、`snapshot.schema.json`、`runtime.schema.json`。Godot 侧在 `contract_validator.gd` 增加对应
`validate_*` 方法，Backend 侧纳入现有 contract 测试。

### 5.4 WebSocket Client（T05）

- 端点：`ws://127.0.0.1:8765/api/v1/ws/editor`（Runtime 为 `/api/v1/ws/runtime`）。
  ADR-005 中的 `/ws` 保留为未实现别名，不提供行为；本设计评审通过后同步更新 ADR-005 §4。
- 状态机：`DISCONNECTED → CONNECTING → CONNECTED → (CLOSING → DISCONNECTED | CONNECTION_LOST)`。
- `CONNECTING` 阶段（含 WS 升级与握手）最长 10s；握手未完成关闭码 4408（退避重连，区别于 4401 认证失败）。
- 发送队列上限 64 帧：`EPHEMERAL` 先丢弃，`PERSISTENT` 保留并标记 `unsynced`；队列满时不阻塞帧循环。
- 连接关闭码：

| 关闭码 | 含义 | 插件行为 |
| --- | --- | --- |
| 1000 | 正常关闭 | 不重连 |
| 4401 | 认证失败/超时 | 停止重连，提示用户检查凭证 |
| 4403 | 无权限（项目/租约） | 停止重连，显示错误 |
| 4408 | 握手或心跳超时 | 退避重连 |
| 4409 | 消息超限 | 修复前不重连 |
| 1011 | 服务端内部错误 | 退避重连 |

- 所有帧收发在 `poll()` 中完成；日志只记录 `message_type`、`action`、`request_id` 前 8 位、耗时，不记录 token 与 payload 全文。

### 5.5 Editor Authentication（T06）

- 首次注册：用户在面板中点击「注册本机编辑器」，插件读取本机 `data/bootstrap.token` 对应值
  （用户手动粘贴或从文件导入），调用 `POST /api/v1/clients`，`client_type = godot_editor`；
  一次性 `client_secret` 写入**用户级**凭证文件 `user://godot_ai_agent/credentials.json`（权限 0600，Windows 使用 ACL 收紧）。
- 凭证绝不出现在项目目录、`project.godot`、导出包、日志或 Git 中；`project_id` 不作为身份。
- 握手认证复用 E2：challenge 60s 一次性，`proof = base64url(HMAC-SHA256(secret, challenge_id + "." + challenge))`。
- Backend 在 WS 内完成：校验 challenge → `ClientService` 验证 → `SessionService.create()` →
  绑定 Editor 信息 → `LeaseService.issue()` → 返回 `SESSION_CREATED`。插件不接触 `gda_` Access Token。
- 失败：连续失败 5 次或服务端返回 `AUTH_CHALLENGE_INVALID` 时进入 ERROR，停止自动重连；写审计 `auth.failed`。
- 撤销：`DELETE /api/v1/sessions/current` 或关闭 Editor 时撤销；服务端撤销优先于插件缓存。

### 5.6 Editor Session（T07）

- 权威：E2 `e2_sessions`（`ACTIVE / EXPIRED / REVOKED / CLOSED`）；E3 不改其状态机。
- Editor 维度信息放绑定表 `e3_editor_sessions`，状态为 `CONNECTED / DISCONNECTED / RECOVERING / CLOSED`
  （E3.md 中的 `SUSPENDED` 落在绑定层，不伪造 Session 状态）。
- 绑定字段：`session_id, editor_instance_id, project_id, godot_version, plugin_version, transport,
  binding_status, connected_at, disconnected_at, last_seen_at, closed_at`。
- 插件缓存 `session_id / expires_at / lease`，但任何「Session 是否有效」的判断以服务端响应为准；
  收到 `SESSION_EXPIRED / SESSION_REVOKED` 立即停止受保护操作并重建。
- 续期：走心跳（服务端续租 + Session renew），插件不自行推算有效期。

### 5.7 Session Lease（T08）

- 表 `e3_session_leases(lease_id, session_id, project_id, fencing_token, status, issued_at, renewed_at,
  expires_at, revoked_at)`；`status ∈ {ACTIVE, RENEWING, EXPIRED, REVOKED}`。
- Fencing Token 由 `e3_project_fencing(project_id, last_token)` 单调分配（项目级），保证旧连接不能覆盖新租约。
- 发放：认证成功时创建；续期：心跳成功且绑定有效；过期：后台清扫 + 心跳超时；撤销：Session 撤销、项目切换、显式断开。
- 受保护操作校验顺序：Session 有效 → 绑定 `CONNECTED` → Lease `ACTIVE` 未过期 → `fencing_token == 最新值`。
  失败分别返回 `SESSION_*` / `LEASE_EXPIRED` / `LEASE_REVOKED` / `FENCING_TOKEN_STALE`。
- 审计：`lease.issued`、`lease.renewed`、`lease.expired`、`lease.revoked`、`lease.rejected`（fail-closed）。
- E3 中标记为 `write` 的 action 只有 `editor.snapshot` 的写入语义与 reserved 命令；读操作仅校验 Session。

### 5.8 Heartbeat（T09）

- 请求：`session.heartbeat`，payload `{sequence, client_time, state_digest, run_status}`；
  响应：`{server_time, session_status, lease:{lease_id, expires_at, fencing_token, status}, next_interval_seconds}`。
- 周期与超时全部配置化：`bridge_heartbeat_interval_seconds`（默认 10）、`bridge_heartbeat_timeout_seconds`（默认 30）、
  `bridge_lease_ttl_seconds`（默认 45）。E3.md 明确这些数值未经实测不作为产品指标，T18 实测后校准。
- 插件侧：连续 3 次未收到响应或超过 `timeout` 判定 `CONNECTION_LOST`，立即暂停受保护操作。
- 服务端：`last_seen_at` 更新；清扫任务把超时绑定置 `DISCONNECTED`、租约置 `EXPIRED`，写审计。
- `sequence` 单调递增；跳号不视为错误，但服务端在响应中返回 `resync_required=true`（由插件触发快照/事件补齐）。

### 5.9 Event Sync（T10）

事件分两类，禁止把 UI 高频状态写入持久事件流：

| 类别 | 示例 | 投递 | 持久化 |
| --- | --- | --- | --- |
| `PERSISTENT` | 项目打开/关闭、项目切换、场景切换、资源保存、插件状态、连接状态 | At-least-once + ACK | `e3_events` |
| `EPHEMERAL` | 选中对象、面板可见性、光标位置 | At-most-once | 不落库 |

- 契约复用 event.schema.json；`sequence` 与 `event_version` 放入 `payload`（契约禁止顶层新增字段）。
- `sequence` 按 `(session_id, direction)` 单调递增；Backend 为下行事件分配，插件为上行事件分配。
- 去重：接收方维护最近 256 个 `event_id` 的环形集合；重复事件直接确认不重复执行。
- 确认：`bridge.events.ack`（批量 `event_ids` + `last_sequence`），服务端写 `acked_at`；
  超过 `bridge_event_ack_timeout_seconds`（默认 30）未确认的下行事件在恢复时重发。
- 补齐：`bridge.events.since`（`after_sequence`，上限 500 条/次）返回事件列表与 `latest_sequence`；
  若请求的 sequence 已被保留策略清理，则返回 `snapshot_required=true`。
- 保留：`bridge_event_retention_days`（默认 7），启动时与每小时清理。

### 5.10 Snapshot（T11）

- 快照由插件生成、Backend 存储，不反向推断。字段：
  `snapshot_id, session_id, project_id, editor_instance_id, snapshot_version, last_event_sequence,
  created_at, editor_status, project_status, active_scene, current_selection, unsaved_resources,
  run_status, import_status, truncated`。
- `unsaved_resources` 为摘要数组 `{path, resource_type}`，不含文件内容；未保存状态必须显式标记。
- 单快照上限 256 KiB，超出时按字段优先级裁剪并置 `truncated=true`（不截断关键字段：项目身份、未保存摘要）。
- 每个 Session 保留最近 5 个快照；`bridge_snapshot_ttl_seconds`（默认 900）后不再用于恢复，只保留审计摘要。
- 恢复时先取最新快照，再补齐 `last_event_sequence` 之后的事件；快照与事件 sequence 必须来自同一 Session。

### 5.11 重连与恢复（T12）

```text
检测断开 → 暂停受保护操作 → 退避重连 → HELLO/AUTH → 校验 Session → 校验 Lease
  → 请求 snapshot → 拉取缺失事件 → 校验 sequence → 恢复 READY 或被拒绝
```

- 退避：0.5s、1s、2s、4s、8s、15s（上限 15s，±20% 抖动），用户手动重连立即重置。
- 恢复分支：

| 服务端状态 | 处理 |
| --- | --- |
| Session `ACTIVE`、绑定存在 | 复用 Session，重新发租约，拉快照与事件 |
| Session `EXPIRED` / `REVOKED` / `CLOSED` | 停止重连，提示需重新认证；不悄悄新建（需用户确认） |
| 项目指纹变化 | 走项目切换流程，重新建立绑定 |
| 事件 sequence 断档且可补齐 | 补齐后恢复 |
| 事件已被清理 | 强制全量快照，标记 `STATE_RECOVERED_FROM_SNAPSHOT` |
| 操作结果未知 | 标记 `UNKNOWN`，禁止自动重试，交用户/E5 决策 |

- 断线不等于操作成功；任何未收到响应的请求在恢复后先查询状态，禁止直接重放。
- 恢复过程写审计 `bridge.recovered` / `bridge.recovery_failed`，并写入诊断摘要。

### 5.12 多 Editor 隔离（T13）

- `editor_instance_id`：插件启用时生成的随机 UUID（进程级，不持久化），只用于区分同一进程内实例与诊断。
- 唯一性键：`(client_id, editor_instance_id)` 在连接期唯一；同一 Editor 重连复用原实例 ID。
- 每个连接独立：Session、Lease、事件 sequence、发送队列、快照链、重连状态；服务端以 `session_id` 为聚合根。
- 同一项目允许多个 Editor 同时连接（只读状态独立）；一旦出现写操作，`fencing_token` 最新者有效，其余返回 `FENCING_TOKEN_STALE`。
- 关闭清理：连接断开 → 绑定 `DISCONNECTED` → 租约保留至 TTL 以便快速重连 → 超时后 `EXPIRED` 并释放 fencing 占用。
- 冲突诊断：`/api/v1/bridge/sessions` 返回按项目分组的连接列表；诊断摘要给出冲突计数。

### 5.13 项目身份与隔离（T14）

- 插件侧：`ProjectSettings.globalize_path("res://")` 取根目录，确认 `project.godot` 存在，读取
  `application/config/name` 与 Godot 版本。
- 服务端不信任客户端路径：重新 `realpath`、检查目录存在与 `project.godot` 可读，并重算指纹比对。
- `project_fingerprint = sha256(realpath(project_root))` 的十六进制摘要；
  `project_id = "prj_" + base32(sha256(realpath)[0:8])`（12 位小写），保证同一路径稳定、路径变化即可检测。
- 临时记录 `e3_projects(project_id, project_root UNIQUE, project_fingerprint, project_name, godot_version,
  created_at, last_seen_at)`；E4 引入正式 Registry 时按同名字段迁移，`project_id` 保持兼容。
- 项目切换：暂停受保护操作 → 旧绑定置 `RECOVERING` → 新项目身份校验 → 撤销旧租约 →
  新绑定 + 新租约 + 新快照 → 恢复 READY。任一步失败进入 ERROR 并停止受保护操作。
- 项目隔离：所有查询强制 `project_id` 过滤；跨项目读取返回 `PROJECT_ACCESS_DENIED`。

### 5.14 Editor State Provider（T15）

| 字段 | 采集方式 | 备注 |
| --- | --- | --- |
| editor_status | 生命周期状态 | READY / ERROR 等 |
| project_identity | ProjectIdentity | project_id / 名称 / 根目录 |
| godot_version | `Engine.get_version_info()` | 启动时缓存 |
| plugin_status | 生命周期 + 版本 | |
| active_scene | `EditorInterface.get_edited_scene_root()` | 场景切换时上报 |
| current_selection | `EditorInterface.get_selection()` | EPHEMERAL，节流 500ms |
| resource_status | 遍历已打开脚本/资源 `get_edited_file` + 未保存标记 | 只报摘要 |
| run_status | `EditorInterface.is_playing_scene()` | 与 Runtime 状态分开 |
| import_status | `EditorFileSystem` 扫描状态摘要 | 只报 `scanning/idle` |

- 变更检测：与上次快照 diff，只上报变化字段；相同状态不上报。
- 采样节流：`state_report_min_interval_seconds`（默认 1s），selection 走 EPHEMERAL 通道。

### 5.15 Runtime Bridge（T16）

- 单独端点 `/api/v1/ws/runtime`，单独客户端身份（`client_type = tool`，名称 `godot-runtime`），
  与 Editor 凭证、Session、权限完全分离；Runtime 只能调用 `bridge.runtime.report` 与只读状态查询。
- 安装方式：插件提供「启用运行时探针」开关，用户显式确认后才通过 `add_autoload_singleton` 注入
  `runtime_bridge.gd`；插件不得静默修改 `project.godot`。
- 注册：Runtime 启动后主动连接，上报 `{runtime_instance_id, project_root, project_fingerprint,
  process_id, started_at, godot_version, build_mode, status}`；服务端校验项目指纹，
  若该项目存在唯一 `CONNECTED` Editor 绑定则关联 `editor_session_id`，否则置空（多 Editor 时不做猜测）。
- 生命周期：游戏停止 → Runtime 发送 `status=STOPPED` → 关闭连接 → 服务端置 `ENDED` 并清理；
  异常退出由心跳超时清理（`bridge_runtime_timeout_seconds`，默认 20）。
- 权限：Runtime 不继承 Editor 的 Lease/Fencing，不可调用任何 `editor.*` 写 action；
  越权返回 `PERMISSION_DENIED` 并写审计。

### 5.16 Editor Bridge UI（T17）

面板（Dock，中文）分组：

- **连接**：Backend 地址（可编辑，仅回环）、在线状态、WS 状态、错误码与详情、重试按钮。
- **会话**：Session ID（截断显示）、状态、过期时间、Lease 状态、fencing token（只读）、最后心跳时间。
- **项目**：项目名称、根目录、Project ID、Godot 版本、未保存资源数。
- **操作**：注册本机编辑器、连接、断开、重新连接、重新同步、复制诊断信息。
- **状态**：`DISCONNECTED / CONNECTING / AUTHENTICATING / CONNECTED / RECONNECTING / RECOVERING / ERROR`。

约束：不显示 token/secret（只显示前后各 4 位）；错误展示 `code + message + 建议动作`；
所有回调只调用服务方法，不直接操作 `WebSocketPeer`。

### 5.17 与 E2 API 的映射

| E2 接口 | E3 用途 |
| --- | --- |
| `GET /api/v1/health/live` | Discovery 存活探测 |
| `GET /api/v1/system/info` | 版本与 API 兼容性校验 |
| `POST /api/v1/clients` | 首次注册 Editor / Runtime 客户端（Bootstrap Token） |
| `POST /api/v1/auth/challenge` | 非 WS 场景（工具、诊断）认证；WS 内由服务端内部调用同一服务 |
| `POST /api/v1/auth/verify` | 同上 |
| `POST /api/v1/sessions` | WS 握手时服务端内部创建；HTTP 场景保留 |
| `GET /api/v1/sessions/current` | 恢复时确认 Session 状态 |
| `POST /api/v1/sessions/current/renew` | 心跳续期（服务端内部或 HTTP） |
| `DELETE /api/v1/sessions/current` | 断开/撤销 |
| `GET /api/v1/projects/access/current` | 面板展示项目授权状态（E3 不阻塞连接） |
| `GET /api/v1/diagnostics/summary` | 新增 `bridge` 块（连接、租约、事件、恢复计数） |

新增只读接口：

- `GET /api/v1/bridge/status`：当前 Session 绑定、Lease、项目身份、未确认事件数（Session Token + `bridge.read`）。
- `GET /api/v1/bridge/sessions`：按项目分组的活动连接（admin 或 `bridge.read` + 项目范围）。

### 5.18 安全与审计

| 要求 | 落地机制 |
| --- | --- |
| E3-SEC-001 Editor 必须认证 | 握手状态机；未认证连接只允许 HELLO/AUTH_RESPONSE，10s 超时关闭 |
| E3-SEC-002 Runtime 独立认证 | 独立端点、独立凭证、独立 Action 集 |
| E3-SEC-003 Session 不可伪造 | 服务端签发 `gds_`，哈希存储；插件不自行生成 ID |
| E3-SEC-004 Lease 过期拒绝 | 每次受保护操作校验租约与过期时间 |
| E3-SEC-005 Fencing 校验 | 项目级单调令牌，服务端比较最新值 |
| E3-SEC-006 项目隔离 | 绑定 + 强制 `project_id` 过滤 + 指纹重算 |
| E3-SEC-007 断开停止操作 | 连接丢失立即置 `paused`，队列丢弃写请求 |
| E3-SEC-008 未保存状态可识别 | 快照/状态中显式 `unsaved` 字段 |
| E3-SEC-009 缓存非实时事实 | 快照带 `created_at` 与 `snapshot_version`，不用于推断 |
| E3-SEC-010 Runtime 不继承写权限 | 独立 Principal 与 Action 白名单 |

新增审计动作：`bridge.connected`、`bridge.disconnected`、`bridge.auth_failed`、`bridge.project_bound`、
`bridge.project_switched`、`lease.issued`、`lease.renewed`、`lease.expired`、`lease.rejected`、
`bridge.recovered`、`bridge.recovery_failed`、`runtime.registered`、`runtime.ended`。
认证、租约与项目绑定类审计 fail-closed；心跳与普通状态上报 fail-open。

### 5.19 错误与恢复策略

新增错误码（写入 `packages/contracts/errors/error-codes.json`，双端同步）：

| 错误码 | 可重试 | 触发场景 | 插件行为 |
| --- | --- | --- | --- |
| `UNKNOWN_MESSAGE_TYPE` | false | 未登记消息类型/action | 丢弃并计数，不重连 |
| `SESSION_SUSPENDED` | true | 绑定处于 RECOVERING | 暂停操作，等待恢复 |
| `LEASE_EXPIRED` | true | 租约过期 | 重新心跳获取租约 |
| `LEASE_REVOKED` | false | 租约被撤销 | 停止操作，重新认证/绑定 |
| `FENCING_TOKEN_STALE` | false | 存在更新的租约 | 停止写操作，提示冲突 |
| `SNAPSHOT_UNAVAILABLE` | true | 无可用快照 | 全量重新同步 |
| `EVENT_SEQUENCE_GAP` | true | 事件无法补齐 | 请求快照重建 |
| `RUNTIME_UNAVAILABLE` | true | Runtime 不在线 | 面板提示，不影响 Editor |

- WS 层错误统一转成 response/error 契约；控制帧错误用 `payload = error 对象`。
- 认证/租约/项目绑定错误进入 ERROR 状态并停止自动重连，避免无限失败循环。
- 任何 `UNKNOWN` 结果只在诊断与 UI 标记，不自动转成成功。

### 5.20 可观测性

- 插件日志字段：`session_id`（截断）、`editor_instance_id`、`project_id`、`message_type`、`action`、
  `request_id`（前 8 位）、`duration_ms`、`error_code`；不记录 token、proof、payload 全文。
- Backend 日志沿用 `request_id` / `correlation_id`；WS 帧日志使用 `correlation_id` 串联握手与恢复。
- `/api/v1/diagnostics/summary` 新增 `bridge` 块：`connections`、`sessions_active`、`leases_active`、
  `events_pending_ack`、`recovery_success`、`recovery_failed`、`fencing_rejections`。
- 指标只做进程内计数，不引入外部监控依赖。

### 5.21 新增配置

```text
bridge_enabled                        true
bridge_ws_path_editor                 /api/v1/ws/editor
bridge_ws_path_runtime                /api/v1/ws/runtime
bridge_handshake_timeout_seconds      10
bridge_heartbeat_interval_seconds     10
bridge_heartbeat_timeout_seconds      30
bridge_lease_ttl_seconds              45
bridge_request_timeout_seconds        15
bridge_ws_max_message_bytes           262144
bridge_outbound_queue_max             64
bridge_event_ack_timeout_seconds      30
bridge_event_retention_days           7
bridge_snapshot_ttl_seconds           900
bridge_snapshot_keep_per_session      5
bridge_runtime_timeout_seconds        20
bridge_rate_limit_per_minute          240
```

插件侧配置放 `EditorSettings`（`godot_ai_agent/backend_url`、`godot_ai_agent/auto_connect`、
`godot_ai_agent/runtime_probe_enabled`），不写入项目文件。

### 5.22 数据模型（迁移 `000007_e3_editor_bridge`）

```text
e3_projects(project_id PK, project_root UNIQUE, project_fingerprint, project_name,
            godot_version, created_at, last_seen_at)

e3_editor_sessions(session_id PK FK e2_sessions, editor_instance_id, project_id FK e3_projects,
                   godot_version, plugin_version, transport, binding_status,
                   connected_at, disconnected_at, last_seen_at, closed_at)
  + 索引 (project_id, binding_status)、(editor_instance_id)

e3_session_leases(lease_id PK, session_id FK e3_editor_sessions, project_id FK e3_projects,
                  fencing_token INTEGER, status, issued_at, renewed_at, expires_at, revoked_at)
  + 索引 (session_id, status)、(project_id, status)

e3_project_fencing(project_id PK, last_token INTEGER)

e3_events(event_id PK, session_id, project_id, event_type, sequence, occurred_at,
          payload, created_at, acked_at)
  + 索引 (session_id, sequence)、(created_at)

e3_snapshots(snapshot_id PK, session_id, project_id, editor_instance_id, snapshot_version,
             last_event_sequence, created_at, payload)
  + 索引 (session_id, created_at)

e3_runtime_instances(runtime_instance_id PK, project_id, editor_session_id NULLABLE,
                     process_id, godot_version, build_mode, started_at, last_seen_at, status)
```

约定沿用 E1/E2：UTC ISO-8601、短字符串状态、外键开启、写入走事务；迁移前自动备份，可降级到 `000006`。

## 6. 任务拆解与批次

批次编号使用 `E3-M1…E3-M6`，与 E2 的 `M6–M10` 不混用。

| 批次 | 任务 | 主要交付 | 测试 |
| --- | --- | --- | --- |
| **E3-M1** | T01 生命周期、T02 服务管理 | `plugin_lifecycle.gd`、`service_registry.gd`、`service.gd`、`plugin_context.gd`、日志扩展 | T01-UT-001…005、T01-IT-001；T02-UT-001…003 |
| **E3-M2** | T03 Discovery、T04 协议、T05 WS Client | `backend_discovery_service.gd`、`protocol_adapter.gd`、`editor_bridge_client.gd`、bridge 契约（7 个 schema + 样例）、`validate_bridge_*` | T03-UT-001…005、T03-IT-001；T04-UT-001…004、T04-CT-001…003；T05-UT-001…005、T05-IT-001 |
| **E3-M3** | T06 认证、T07 Session、T08 Lease、T17 UI | `app/ws/editor.py`、`modules/project` / `modules/editor_session` / `modules/lease`、迁移 `000007`（项目/绑定/租约/fencing）、`connection_panel.gd` | T06-UT-001…005、T06-IT-001；T07-UT-001…004、T07-IT-001；T08-UT-001…006、T08-IT-001；T17-UT-001…003、T17-IT-001 |
| **E3-M4** | T09 心跳、T10 事件、T11 快照 | `heartbeat_service.gd`、`event_sync_service.gd`、`snapshot_service.gd`、`modules/{bridge_event,snapshot}`、迁移补充事件/快照表 | T09-UT-001…004、T09-IT-001；T10-UT-001…005、T10-IT-001；T11-UT-001…004、T11-IT-001 |
| **E3-M5** | T12 恢复、T13 多 Editor、T14 项目身份 | `reconnection_service.gd`、`project_identity.gd`、恢复流程、`/bridge/status`、`/bridge/sessions`、诊断扩展 | T12-UT-001…005、T12-IT-001…002；T13-UT-001…004、T13-IT-001；T14-UT-001…005、T14-IT-001 |
| **E3-M6** | T15 状态采集、T16 Runtime、T18 集成测试与收尾 | `editor_state_provider.gd`、`app/ws/runtime.py`、`modules/runtime`、`runtime_bridge.gd`、Godot 测试运行器、`check_all` 新阶段、E3 验收报告 | T15-UT-001…004；T16-UT-001…004、T16-IT-001；E3-IT-001…014；安全测试 |

批次依赖：M1 → M2 → M3 → M4 → M5 → M6；每批结束运行 `ruff`、`pytest`、`check_all` 并更新进度文档。

### 6.1 测试组织

- Backend：`apps/backend/tests/{unit,integration,contract}/test_e3_*.py`；WS 测试使用 Starlette `TestClient.websocket_connect`。
- 插件单元测试：新增轻量运行器 `apps/godot-plugin/tests/run_tests.gd`（`SceneTree` 脚本，断言 + 退出码），
  不引入 GUT 依赖；用例放 `apps/godot-plugin/tests/e3/`。
- 端到端：pytest fixture 在临时端口启动 uvicorn，设置 `GODOT_AI_BACKEND_URL`，再以
  `godot --headless --path apps/godot-plugin --script res://tests/e3/run_bridge_e2e.gd` 运行；
  找不到 Godot 二进制时 `SKIP`（沿用 `GODOT_BIN`）。
- `scripts/testing/check_all.py` 新增阶段「Godot Bridge Tests」：Godot 缺失时 SKIP，后端未启动时由 fixture 自行拉起。

### 6.2 集成测试清单（E3-T18）

| 编号 | 场景 | 预期 |
| --- | --- | --- |
| E3-IT-001 | 插件启用/关闭/重复启用（headless） | 无重复服务与残留连接 |
| E3-IT-002 | Discovery 五种状态 | UI 状态与错误码正确 |
| E3-IT-003 | 握手 → 认证 → Session → Lease | 返回完整 `SESSION_CREATED`，审计落库 |
| E3-IT-004 | 非法消息/未知 action/超大帧 | 拒绝且不断言成功，关闭码正确 |
| E3-IT-005 | 心跳续租与超时 | 在线/离线判定准确，租约按时过期 |
| E3-IT-006 | 事件发布、重复、确认、补齐 | 不重复执行，sequence 连续 |
| E3-IT-007 | 快照生成与恢复 | 未保存状态可见，sequence 对齐 |
| E3-IT-008 | 断线重连（Session 有效） | 复用 Session 并恢复 |
| E3-IT-009 | Session 过期/撤销 | 停止受保护操作，要求重新认证 |
| E3-IT-010 | 两个 Editor 同时连接 | Session/Lease/事件互不污染 |
| E3-IT-011 | 项目切换 | 旧绑定撤销，新项目重新绑定 |
| E3-IT-012 | Runtime 注册/停止/异常退出 | 独立通道，Editor 不受影响 |
| E3-IT-013 | 旧 Fencing Token 操作 | 返回 `FENCING_TOKEN_STALE` |
| E3-IT-014 | 故障注入（后端重启、WS 异常断开、事件丢失） | 不产生假成功，恢复或明确失败 |

## 7. 待确认项（评审时决定）

| 编号 | 问题 | 建议决策 |
| --- | --- | --- |
| E3-Q1 | 是否为 Bridge 另建业务 Envelope | 不另建；控制帧新增，业务帧复用 Shared Contracts 1.0 |
| E3-Q2 | WebSocket 路径 | `/api/v1/ws/editor` 与 `/api/v1/ws/runtime`；ADR-005 的 `/ws` 保留未实现别名 |
| E3-Q3 | Editor 凭证存放在哪里 | `user://godot_ai_agent/credentials.json`（0600），用户级，不进项目与 Git |
| E3-Q4 | Session/Lease 在 WS 内还是 HTTP 创建 | 握手内一次完成，插件不接触 Access Token；HTTP 接口保留给工具与诊断 |
| E3-Q5 | E3.md 的 `SUSPENDED` 状态如何落地 | 不改 E2 Session 状态机，落在 `e3_editor_sessions.binding_status` |
| E3-Q6 | 项目 ID 生成方式 | `prj_` + `sha256(realpath)[0:8]` base32；E4 迁移为正式 Registry 并保持 ID 兼容 |
| E3-Q7 | 连接时是否强制 E2 Project Access | E3 不阻塞连接，只展示；受保护写操作（E5+）强制 |
| E3-Q8 | 多 Editor 同项目的写冲突 | 允许并存，写权限由项目级 fencing token 唯一化 |
| E3-Q9 | Runtime 探针安装与身份类型 | 用户显式启用 autoload；复用 `client_type=tool` 的独立凭证 |
| E3-Q10 | Godot 侧测试框架 | 自建轻量 headless 运行器，不引入 GUT；接入 `check_all` 可选阶段 |
| E3-Q11 | 心跳/租约参数 | 全部配置化，默认值仅作起点，T18 实测后校准 |
| E3-Q12 | 事件持久化范围 | 仅 `PERSISTENT` 事件入库；`EPHEMERAL` 不落库，默认保留 7 天 |

## 8. 验收映射

| 目标 | 任务 | 证据 |
| --- | --- | --- |
| E3-G01 | T01 / T02 | T01-UT/IT、T02-UT、E3-IT-001 |
| E3-G02 | T03 | T03-UT/IT、E3-IT-002 |
| E3-G03 | T04 / T05 | T04-UT/CT、T05-UT/IT、E3-IT-003/004 |
| E3-G04 | T06 | T06-UT/IT、安全测试 |
| E3-G05 | T07 | T07-UT/IT、E3-IT-009 |
| E3-G06 | T09 | T09-UT/IT、E3-IT-005 |
| E3-G07 | T08 | T08-UT/IT、E3-IT-013 |
| E3-G08 | T10 | T10-UT/IT、E3-IT-006 |
| E3-G09 | T11 / T12 | T11/T12 测试、E3-IT-007/008/014 |
| E3-G10 | T13 | T13-UT/IT、E3-IT-010 |
| E3-G11 | T14 | T14-UT/IT、E3-IT-011 |
| E3-G12 | T15 | T15-UT、快照字段校验 |
| E3-G13 | T16 | T16-UT/IT、E3-IT-012 |
| E3-G14 | T18 | E3-IT-001…014、pytest + check_all + 验收报告 |

## 9. 风险与后续

| 编号 | 风险 | 影响 | 应对 |
| --- | --- | --- | --- |
| E3-R01 | Godot WebSocket API 版本差异 | 连接不稳定 | 固定 Godot 4.5.1，headless 实测优先于接口推演 |
| E3-R02 | WS 中断 | 操作中断 | 退避重连 + 快照/事件恢复 |
| E3-R03 | Session 过期 | 状态不一致 | Lease + 心跳续期，服务端权威 |
| E3-R04 | 旧连接继续执行 | 并发冲突 | 项目级 fencing token |
| E3-R05 | 多 Editor 状态污染 | 错误项目操作 | Session + 项目双隔离，强制 `project_id` 过滤 |
| E3-R06 | 事件丢失 | 状态不一致 | Snapshot + `events.since` + `snapshot_required` |
| E3-R07 | 未保存资源被忽略 | 数据覆盖 | 编辑器状态为权威，快照显式标记未保存 |
| E3-R08 | Runtime 权限过大 | 安全风险 | 独立认证与 Action 白名单 |
| E3-R09 | 凭证文件泄漏 | 身份冒用 | 用户级存储、0600、脱敏日志、撤销接口 |
| E3-R10 | 事件/快照表增长 | 数据库膨胀 | 保留策略、启动与每小时清理、快照保留 5 份 |
| E3-R11 | 心跳参数不合理 | 误判离线/空转 | 全部配置化，T18 压测校准 |
| E3-R12 | headless 无法覆盖 UI | 面板缺陷遗漏 | UI 只做状态映射；关键状态机在脚本层单测 |

E3 验收通过后进入 E4 Project & Workflow Systems。E4 的 Project Registry 直接复用
`e3_projects` 与 `project_id`；后续所有编辑器操作必须经 Editor Bridge，Backend 不得模拟编辑器内部状态。
