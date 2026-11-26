# Asset Registry（E11-T11）

所有资产都必须记录来源与许可；禁止来源不明的外部素材。

| 资产 | 路径 | 类型 | 来源 | 许可 | 用途 |
| --- | --- | --- | --- | --- | --- |
| 玩家占位图 | `assets/characters/player.svg` | 矢量 | 项目内生成 | 项目内部 | Player Sprite2D |
| 敌人占位图 | `assets/characters/enemy.svg` | 矢量 | 项目内生成 | 项目内部 | PatrolEnemy Sprite2D |
| 地形图集 | `assets/tilesets/tiles.svg` | 矢量（3 tiles） | 项目内生成 | 项目内部 | Ground / Platforms TileMapLayer |
| 地刺 | `assets/environments/spikes.svg` | 矢量 | 项目内生成 | 项目内部 | SpikeTrap |
| 金币 | `assets/ui/coin.svg` | 矢量 | 项目内生成 | 项目内部 | Collectible（coin） |
| 宝石 | `assets/ui/gem.svg` | 矢量 | 项目内生成 | 项目内部 | Collectible（gem） |
| 跳跃音效 | `assets/audio/jump.wav` | 音频（程序生成正弦） | 项目内生成 | 项目内部 | 跳跃反馈 |
| 受伤音效 | `assets/audio/hurt.wav` | 音频（程序生成方波） | 项目内生成 | 项目内部 | 受伤反馈 |
| 收集音效 | `assets/audio/collect.wav` | 音频（程序生成正弦） | 项目内生成 | 项目内部 | 收集反馈 |
| 背景音乐 | `assets/audio/bgm.wav` | 音频（程序生成琶音） | 项目内生成 | 项目内部 | 关卡背景音乐 |
| 项目图标 | `icon.svg` | 矢量 | 项目内生成 | 项目内部 | 窗口图标 |

## 处理与导入

- SVG 由 Godot 默认导入为 Texture2D，不进行外部压缩。
- WAV 采样率 22050 Hz、16-bit、单声道；背景音乐设置为前向循环。
- 资源路径稳定，不允许在脚本中硬编码绝对路径或 `user://` 之外的路径。
- 视觉动画（跳跃尘土、受击闪烁、收集缩放）由 GDScript Tween 生成，不依赖外部动画资源。

## 缺失项

- 无真实美术资源（占位图足以验证系统级链路）。
- 无授权受限的第三方素材。
