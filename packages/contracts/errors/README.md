# 错误编码规范

错误对象结构由 [error.schema.json](error.schema.json) 定义，错误码清单由
[error-codes.json](error-codes.json) 维护。

## 规则

1. `code` 全大写下划线，长度 3–64，例如 `INVALID_REQUEST`。
2. `message` 面向用户可读，不得包含堆栈、密钥、绝对路径。
3. `details` 为机器可读的补充信息，允许为空对象，禁止放敏感数据。
4. `retryable` 表示调用方是否可以在不改变请求的情况下重试。
5. `correlation_id` 必须回填请求链路 ID，便于串联日志。
6. 新增错误码必须先更新 `error-codes.json`，再在代码中使用。

## 已定义错误码

| code | retryable | HTTP | 含义 |
| --- | --- | --- | --- |
| `PROTOCOL_VERSION_UNSUPPORTED` | 否 | 400 | 协议版本不受支持 |
| `INVALID_REQUEST` | 否 | 400 | 请求结构不合法 |
| `VALIDATION_FAILED` | 否 | 422 | payload 业务校验失败 |
| `UNAUTHORIZED` | 否 | 401 | 认证失败 |
| `NOT_FOUND` | 否 | 404 | 资源不存在 |
| `CONFLICT` | 否 | 409 | 状态冲突 |
| `RESOURCE_LOCKED` | 是 | 423 | 资源被锁定 |
| `RATE_LIMITED` | 是 | 429 | 触发限流 |
| `TIMEOUT` | 是 | 504 | 下游超时 |
| `DEPENDENCY_UNAVAILABLE` | 是 | 503 | 依赖不可用 |
| `NOT_IMPLEMENTED` | 否 | 501 | 尚未实现 |
| `INTERNAL_ERROR` | 否 | 500 | 内部错误 |
