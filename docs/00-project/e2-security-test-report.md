# E2 安全测试报告

- **阶段：** E2 Backend Services
- **日期：** 2026-11-18
- **范围：** 认证、Token、Session、Project Access、统一授权、请求保护、审计与诊断
- **结论：** 12 项安全要求全部 PASS，未发现未关闭的严重安全缺陷

## 1. 测试环境

| 项 | 值 |
| --- | --- |
| Python | 3.14.2 |
| FastAPI / SQLAlchemy | 当前锁定版本（见 `apps/backend/pyproject.toml`） |
| 数据库 | SQLite（WAL，临时文件） |
| 执行方式 | `pytest`（asyncio auto），HTTP 通过 `httpx.ASGITransport` |
| 用例位置 | `tests/integration/test_security.py`、`test_audit.py`、`test_audit_events.py` |

## 2. 安全要求与结果

| # | 安全要求 | 验证方式 | 结果 |
| --- | --- | --- | --- |
| 1 | 未认证请求无法访问受保护接口 | `test_unauthenticated_requests_are_rejected`：`/system/status`、`/sessions/current`、`/projects/access/current`、`/diagnostics/summary` 均 401 `AUTH_REQUIRED` | PASS |
| 2 | 过期 Token 无法访问 | `test_expired_token_is_rejected`：`access_token_ttl_seconds=0` 后访问受保护接口返回 `TOKEN_EXPIRED` | PASS |
| 3 | 已撤销 Token 无法访问 | `test_revoked_token_is_rejected`：刷新轮换后重放旧 Token 返回 `TOKEN_REVOKED` | PASS |
| 4 | Session 不能跨 Client 使用 | `test_session_cannot_cross_client`：未获授权的第三方 Session 查询项目访问返回 `PROJECT_ACCESS_DENIED` | PASS |
| 5 | Project ID 篡改不能越权 | `test_project_id_tampering_is_denied`：持有 `proj_alpha` 访问后查询 `proj_beta` 返回 `PROJECT_ACCESS_DENIED` | PASS |
| 6 | 未知权限默认拒绝 | `test_unknown_action_is_denied_by_default`：未知 Action 决策为 `DENY`（`capability_missing`） | PASS |
| 7 | 不可信客户端不能自行授予权限 | `test_untrusted_client_cannot_self_grant`：viewer 尝试授予 owner 返回 `PERMISSION_DENIED` | PASS |
| 8 | Challenge 不能重复使用 | `test_challenge_cannot_be_reused`：同一 challenge 第二次校验返回 `AUTH_CHALLENGE_INVALID` | PASS |
| 9 | Token 不进入日志 | `test_tokens_never_enter_logs`：捕获结构化日志，Access/Session Token 与 client_secret 均不出现 | PASS |
| 10 | 非法大请求不会耗尽 Backend 资源 | `test_oversized_request_is_rejected`：2 MiB 请求体返回 413 `REQUEST_TOO_LARGE` | PASS |
| 11 | API 默认不监听公网接口 | `test_api_binds_loopback_by_default`：默认 `127.0.0.1`；`0.0.0.0` 被配置校验拒绝（`ConfigError`） | PASS |
| 12 | 诊断接口不能泄露敏感数据 | `test_diagnostics_does_not_leak_sensitive_data`：响应不含 Secret、Session Token、数据库连接串 | PASS |

## 3. 审计与故障注入

| 场景 | 用例 | 结果 |
| --- | --- | --- |
| 审计事件正常记录 | `test_audit_records_core_lifecycle`：注册、认证、Session、授予、撤销事件齐全，含 `correlation_id` | PASS |
| 授权拒绝留痕 | `test_denied_authorization_is_audited`：`authorization.denied`、`reason=role_denied`、角色为 `viewer` | PASS |
| 审计字段脱敏 | `test_sanitize_details_allows_only_whitelist` / `test_sanitize_details_redacts_registered_secret` | PASS |
| 审计落库不含 Secret/Token | `test_audit_details_never_contain_secrets` | PASS |
| 敏感操作审计失败 | `test_sensitive_audit_failure_is_fail_closed`：返回 `AUDIT_FAILED` | PASS |
| 普通事件审计失败 | `test_non_sensitive_audit_failure_is_fail_open`：输出 ERROR 后继续 | PASS |
| 诊断高风险调用留痕 | `test_diagnostics_access_is_audited_as_high_risk`：`high_risk.call` | PASS |
| 审计 fail-closed 可配置 | `test_fail_closed_can_be_disabled` | PASS |

## 4. 残余风险

| 事项 | 说明 | 处置 |
| --- | --- | --- |
| 限流为进程内实现 | 单进程有效；多 worker 会放大配额（E2-Q4） | 引入多 worker 前切换共享存储 |
| 项目注册表尚未引入 | 未知项目一律 `PROJECT_ACCESS_DENIED` | E4 引入项目实体后接入 |
| 审计表持续增长 | 当前无归档策略 | E12 或运维阶段补充保留策略 |
| 端口仅绑定回环 | 符合本地优先架构；如需远程访问必须引入 TLS 与额外认证 | 保持现状，跨机场景不在 E2 范围 |

## 5. 结论

E2 安全测试 12 项全部通过，认证、授权、限流、请求保护、审计与诊断均按设计工作，
未发现未关闭的严重安全缺陷。
