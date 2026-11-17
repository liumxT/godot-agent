# Shared Contracts（协议 1.0）

Backend 与 Godot Plugin 之间唯一的数据协议事实源。任何跨进程通信必须遵守本目录定义。

## 目录

```
packages/contracts/
├── api/       请求与响应
├── events/    事件
├── errors/    错误结构与错误码
├── common/    协议常量
├── schemas/   样例与校验清单（两端共用）
└── README.md
```

## 基础约束

1. 所有消息必须携带 `protocol_version`，当前为 `1.0`。
2. 请求必须携带 `request_id`；一次操作链路用 `correlation_id` 串联。
3. 事件必须携带全局唯一 `event_id`。
4. 未知字段一律拒绝（`additionalProperties: false`），前向兼容通过升版本解决。
5. 时间统一 UTC，格式 `YYYY-MM-DDTHH:MM:SSZ`，可选小数秒。
6. 错误统一使用 `errors/error.schema.json` 的结构。

## 标识符

| 字段 | 规则 | 建议前缀 |
| --- | --- | --- |
| `request_id` | `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$` | `req_` |
| `correlation_id` | 同上 | `cor_` |
| `session_id` | 同上 | `ses_` |
| `project_id` | 同上 | `prj_` |
| `event_id` | 同上 | `evt_` |

前缀是约定而非强制；唯一性由生成方保证。

## 请求

```json
{
  "protocol_version": "1.0",
  "request_id": "req_01HZX",
  "correlation_id": "cor_01HZX",
  "timestamp": "2026-11-17T10:00:00Z",
  "session_id": "ses_01HZX",
  "project_id": "prj_01HZX",
  "action": "project.scan",
  "payload": {}
}
```

- `action` 采用 `namespace.verb` 小写点分格式。
- `payload` 为对象，具体结构由各 action 的契约定义，不在本阶段冻结。

## 响应

```json
{
  "protocol_version": "1.0",
  "request_id": "req_01HZX",
  "success": true,
  "data": {},
  "error": null
}
```

- `success: true` 时 `error` 必须为 `null`。
- `success: false` 时 `error` 必须是合法错误对象，`data` 允许为 `null`。

## 错误

```json
{
  "code": "INVALID_REQUEST",
  "message": "action is required",
  "details": {"field": "action"},
  "retryable": false,
  "correlation_id": "cor_01HZX"
}
```

错误码清单见 [errors/error-codes.json](errors/error-codes.json)，规范说明见 [errors/README.md](errors/README.md)。

## 事件

```json
{
  "protocol_version": "1.0",
  "event_id": "evt_01HZX",
  "event_type": "project.scanned",
  "timestamp": "2026-11-17T10:00:01Z",
  "source": "backend",
  "session_id": "ses_01HZX",
  "project_id": "prj_01HZX",
  "correlation_id": "cor_01HZX",
  "payload": {}
}
```

## 样例与两端校验

[schemas/manifest.json](schemas/manifest.json) 列出全部样例及期望结果：

- Backend：`apps/backend/tests/contract/test_protocol_samples.py`
- Plugin：`apps/godot-plugin/tests/contract_probe/plugin.gd`

两端必须对同一份清单得出相同结论，这是 E0-T05 的验收方式。

运行方式：

```powershell
# Backend
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/contract -q

# Plugin（编辑器模式，日志中出现 "contract samples: 11/11 passed"）
& "<Godot 4.5.1 console exe>" --headless --editor --path apps/godot-plugin `
  --quit-after 600 -- --contract-test
```

## 版本演进

- 兼容变更（新增可选字段）→ 升次版本 `1.1`，接收方必须容忍。
- 破坏性变更（改字段语义、删除字段、必填化）→ 升主版本 `2.0`，不兼容共存。

本阶段仅冻结 `1.0`，`additionalProperties: false` 表示当前不接受未定义字段。
