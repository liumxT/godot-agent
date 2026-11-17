# Secrets 管理规范（E0-T07）

## 1. 原则

1. 凭证（API Key、Token、密码、私钥）**只存操作系统凭证库**。
2. 配置文件（`.env`）、代码、数据库、日志、错误详情中不得出现明文凭证。
3. 缺失必需凭证时显式失败（`ConfigError`），不允许静默降级或空值运行。
4. 运行时只按名称读取，不缓存到可序列化配置对象中。

## 2. 存储位置

| 平台 | 后端 |
| --- | --- |
| Windows | Credential Manager（`keyring` 默认后端） |
| macOS | Keychain |
| Linux | Secret Service（GNOME Keyring / KWallet） |

实现：`apps/backend/src/infrastructure/secrets/store.py`，服务名 `godot-ai-agent`。

## 3. 命名规范

- 格式：`<provider>.<用途>`，仅允许 `A-Z a-z 0-9 _ . -`，最长 128 字符。
- 示例：`openai.api_key`、`anthropic.api_key`、`godot.bridge_token`。
- 名称非法时直接抛 `ConfigError`，避免写入凭证库的脏键。

## 4. 访问方式

```python
from infrastructure.secrets import KeyringSecretStore, require_secret

store = KeyringSecretStore()
api_key = require_secret(store, "openai.api_key")  # 缺失 → ConfigError
```

- 测试使用内存实现（`tests/unit/test_secrets.py` 的 `MemorySecretStore`），
  不写入真实凭证库。
- 日志与错误输出只能使用 `redact(value)`（固定返回 `***`），禁止打印原值。

## 5. 首次配置与轮换

1. 首次配置：由用户在系统凭证管理器中新增条目，或由安装器/设置页调用
   `store.set(name, value)`（E11 提供界面）。
2. 轮换：覆盖写入新值即可；旧值不保留在配置或数据库中。
3. 删除：`store.delete(name)`，不存在的条目视为成功（幂等）。
4. 备份：凭证库由操作系统负责，不纳入项目数据库备份范围。

## 6. 失败处理

| 场景 | 行为 |
| --- | --- |
| 缺少 `keyring` 依赖 | `ConfigError`，提示安装 `keyring` |
| 凭证不存在 | `ConfigError`，`details.secret` 给出名称 |
| 凭证库读写异常 | `ConfigError`，仅记录名称，不记录值 |

## 7. 验收

```powershell
cd apps/backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_secrets.py -q
```

覆盖：必需密钥读取、缺失报错、脱敏、非法名称拒绝、keyring 依赖可用。
