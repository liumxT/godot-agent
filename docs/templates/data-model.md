# 数据模型文档

| 项 | 内容 |
| --- | --- |
| 模型/表名 | <例：tasks> |
| 归属模块 | <模块名> |
| 迁移版本 | <例：000003_add_tasks_table> |
| 状态 | Draft / Review / Stable |
| 最后更新 | <YYYY-MM-DD> |

## 1. 用途

<该表承载什么业务数据，写入与读取的主要场景。>

## 2. 字段

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | TEXT | PK | <生成规则> |
| `<field>` | <类型> | NOT NULL / UNIQUE / DEFAULT | <语义> |
| `created_at` | DATETIME | NOT NULL | UTC |
| `updated_at` | DATETIME | NOT NULL | UTC |

## 3. 索引与约束

| 名称 | 类型 | 字段 | 用途 |
| --- | --- | --- | --- |
| `<idx_name>` | INDEX / UNIQUE | <字段> | <查询场景> |

## 4. 关系

| 关系 | 目标表 | 外键 | 删除策略 |
| --- | --- | --- | --- |
| <一对多> | <表名> | `<field>` | CASCADE / RESTRICT |

## 5. 迁移

- 新增：`<00000x_name>`，包含 upgrade / downgrade。
- 数据兼容：<是否回填、是否可空、默认值>
- 回滚风险：<说明>

## 6. Repository

- 归属：<模块>/repositories
- 禁止：<其他模块直接访问本表>
- 事务：<单次事务包含的写入>

## 7. 保留与备份

- 保留策略：<永久/按天>
- 是否纳入备份：<是/否>
- 敏感字段：<无；如有，说明加密方式，禁止明文凭证>

## 8. 测试

| 测试编号 | 内容 | 位置 |
| --- | --- | --- |
| <IT-xxx> | <建表/约束/迁移幂等> | `tests/integration/...` |
