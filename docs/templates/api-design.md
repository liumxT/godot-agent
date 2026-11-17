# API / 事件设计文档

| 项 | 内容 |
| --- | --- |
| 接口名称 | <例：task.create> |
| 协议版本 | <1.0> |
| 类型 | HTTP / WebSocket 请求 / 事件 |
| 状态 | Draft / Review / Stable |
| 最后更新 | <YYYY-MM-DD> |

## 1. 用途

<谁在什么场景调用，解决什么问题。>

## 2. 定义来源

- 请求 Schema：`packages/contracts/api/request.schema.json`
- 响应 Schema：`packages/contracts/api/response.schema.json`
- 事件 Schema：`packages/contracts/events/event.schema.json`

本文只描述字段语义，冲突时以 Schema 为准。

## 3. 请求

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `action` | string | 是 | <动作名> |
| `payload.<field>` | <类型> | <是/否> | <语义、取值范围> |

示例：

```json
{
  "protocol_version": "1.0",
  "request_id": "req-...",
  "action": "task.create",
  "payload": {}
}
```

## 4. 响应

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `data.<field>` | <类型> | <语义> |

## 5. 错误

| 错误码 | HTTP/关闭码 | 可重试 | 触发条件 |
| --- | --- | --- | --- |
| `<ERROR_CODE>` | <400> | 是/否 | <条件> |

错误码必须已登记在 `packages/contracts/errors/error-codes.json`。

## 6. 幂等与重试

- 幂等键：<字段/规则>
- 重复请求处理：<返回缓存结果 / 拒绝 / 忽略>
- 建议重试策略：<次数、间隔>

## 7. 权限与安全

<鉴权要求、允许的来源、敏感字段处理。>

## 8. 兼容性

- 新增字段：<向后兼容策略>
- 破坏性变更：<版本升级方式>
