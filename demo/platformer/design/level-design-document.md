# Level Design Document（E11-T02）

## 1. 关卡概览

| 项 | 值 |
| --- | --- |
| 关卡键 | LEVEL-01 |
| 名称 | Level 01 - Green Hills |
| 尺寸 | 160 × 24 tiles（16 px/tile） |
| 主题 | 草地与岩石平台 |
| 目标时长 | 3–5 分钟 |
| 检查点 | 无（Demo 采用单段关卡 + 快速重试） |

## 2. 坐标与区段

| 区段 | X 范围（tile） | 内容 |
| --- | --- | --- |
| TUTORIAL | 0–24 | 平地、第一段 2 格高台、提示牌 |
| JUMPS | 24–52 | 三段递进平台，间距 3/4/5 tiles |
| TRAPS | 52–80 | 地刺 ×2、窄平台、可回退通道 |
| ENEMY | 80–108 | 巡逻敌人 ×2，中间有安全落点 |
| COLLECT | 108–136 | 金币弧线、高台宝石 |
| GOAL | 136–160 | 终点旗帜与围栏 |

## 3. 平台布局

- 地面 y=20，厚度 2 tiles。
- 浮空平台高度：y=17、y=14、y=11。
- 平台宽度 4–8 tiles，保证落点容错。
- 高台宝石上方无天花板，避免跳跃被卡。

## 4. 陷阱

| 位置 | 类型 | 伤害 | 说明 |
| --- | --- | --- | --- |
| x=58, y=19 | 地刺 ×3 | 1 | 地面缺口前的低风险陷阱 |
| x=72, y=19 | 地刺 ×5 | 1 | 窄平台落地惩罚 |
| x=96, y=16 | 地刺 ×2 | 1 | 敌人区段高台边缘 |

陷阱必须使用真实碰撞体（Area2D + CollisionShape2D），不能只用外观贴图。

## 5. 敌人位置

| ID | 位置 | 巡逻范围 | 生命 |
| --- | --- | --- | --- |
| ENEMY-01 | x=86, y=19 | 80–94 | 2 |
| ENEMY-02 | x=104, y=19 | 98–110 | 2 |

## 6. 收集物

| 类型 | 数量 | 位置 | 分值 |
| --- | --- | --- | --- |
| coin | 12 | 跳台弧线与地面路径 | 10 |
| gem | 3 | 三个高台顶点 | 50 |

预计单次通关分数：12×10 + 3×50 = 270；最佳分数目标 ≥ 270。

## 7. 检查点

Demo 不设检查点：死亡后由结算界面 Retry，直接重载 LEVEL-01，
避免引入存档点复杂度，同时符合「失败反馈快速」的设计目标。

## 8. 终点

- Goal Area2D 位于 x=150，y=17–20。
- 进入后触发 `goal_reached` → GameFlowManager VICTORY。
- 终点前留 6 tiles 安全平地，避免玩家在终点边缘被敌人击杀。

## 9. 可验证性

关卡节点结构必须可由 E3 Editor Bridge 查询：

```text
Level01 (Node2D)
├── TileMapLayer (Ground)
├── TileMapLayer (Platforms)
├── Traps (Node2D)
│   └── Spikes
├── Enemies (Node2D)
│   └── PatrolEnemy ×2
├── Collectibles (Node2D)
├── Goal (Area2D)
└── PlayerSpawn (Marker2D)
```
