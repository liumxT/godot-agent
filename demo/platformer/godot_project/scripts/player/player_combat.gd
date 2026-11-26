extends Node
## 玩家攻击：冷却、有效帧与 Hitbox 开关。

var player: CharacterBody2D
var config: PlayerConfig
var hitbox: Variant

var _cooldown_left: float = 0.0
var _active_left: float = 0.0
var _attacking: bool = false


func setup(owner_player: CharacterBody2D, player_config: PlayerConfig) -> void:
	player = owner_player
	config = player_config
	hitbox = player.get_node("Hitbox")
	hitbox.damage = config.attack_damage
	hitbox.source_id = str(player.name)


func _process(delta: float) -> void:
	if _cooldown_left > 0.0:
		_cooldown_left = maxf(_cooldown_left - delta, 0.0)
	if _active_left > 0.0:
		_active_left = maxf(_active_left - delta, 0.0)
		if _active_left == 0.0 and hitbox != null:
			hitbox.deactivate()
			_attacking = false


func try_attack(facing: int) -> bool:
	if config == null or hitbox == null:
		return false
	if _cooldown_left > 0.0 or _attacking:
		return false
	_cooldown_left = config.attack_cooldown
	_active_left = config.attack_active_window
	_attacking = true
	hitbox.position = Vector2(26.0 * facing, 0.0)
	hitbox.activate()
	_lunge(facing)
	return true


func is_attacking() -> bool:
	return _attacking


func _lunge(facing: int) -> void:
	if player == null:
		return
	var sprite := player.get_node_or_null("Sprite2D") as Sprite2D
	if sprite == null:
		return
	var tween := create_tween()
	sprite.position.x = 4.0 * facing
	tween.tween_property(sprite, "position:x", 0.0, 0.12)
