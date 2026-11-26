class_name PlayerConfig
extends Resource
## 玩家可配置参数：由 player.tscn 引用，脚本不得硬编码。

@export var max_speed: float = 220.0
@export var acceleration: float = 1600.0
@export var friction: float = 1800.0
@export var air_control: float = 0.6
@export var gravity: float = 1200.0
@export var max_fall_speed: float = 900.0
@export var jump_velocity: float = -420.0
@export var jump_buffer: float = 0.1
@export var coyote_time: float = 0.08
@export var max_health: int = 3
@export var invulnerability: float = 1.0
@export var knockback: float = 160.0
@export var attack_damage: int = 1
@export var attack_cooldown: float = 0.35
@export var attack_active_window: float = 0.12
