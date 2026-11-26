extends "res://scripts/enemies/enemy_base.gd"
## 巡逻敌人：边界/悬崖转向，进入攻击范围后攻击。

@export var patrol_range: float = 64.0
@export var detect_range: float = 140.0
@export var attack_range: float = 48.0
@export var attack_cooldown: float = 0.8

var _origin_x: float = 0.0
var _direction: int = -1
var _cooldown_left: float = 0.0
var _player: Variant = null

@onready var floor_check: RayCast2D = $FloorCheck


func _ready() -> void:
	super()
	_origin_x = global_position.x
	_player = get_tree().get_first_node_in_group("player")


func _physics_process(delta: float) -> void:
	super(delta)
	if dead:
		return
	_cooldown_left = maxf(_cooldown_left - delta, 0.0)
	_refresh_player()
	if _can_attack():
		velocity.x = 0.0
		_face(_player.global_position.x)
		if _cooldown_left == 0.0:
			_attack()
	else:
		_patrol()
	move_and_slide()
	if is_on_wall():
		_direction *= -1
	if is_on_floor() and not floor_check.is_colliding():
		_direction *= -1


func _refresh_player() -> void:
	if _player != null and is_instance_valid(_player):
		return
	_player = get_tree().get_first_node_in_group("player")


func _can_attack() -> bool:
	if _player == null:
		return false
	if _player.has_method("is_dead") and _player.is_dead():
		return false
	var offset: Vector2 = _player.global_position - global_position
	return absf(offset.x) <= attack_range and absf(offset.y) <= 40.0


func _patrol() -> void:
	velocity.x = _direction * move_speed
	if global_position.x < _origin_x - patrol_range:
		_direction = 1
	elif global_position.x > _origin_x + patrol_range:
		_direction = -1
	_face(global_position.x + _direction)


func _face(target_x: float) -> void:
	if target_x < global_position.x:
		_direction = -1
		sprite.flip_h = true
	else:
		_direction = 1
		sprite.flip_h = false


func _attack() -> void:
	_cooldown_left = attack_cooldown
	hitbox.position = Vector2(20.0 * _direction, 0.0)
	hitbox.activate()
	var tween := create_tween()
	tween.tween_property(sprite, "scale", Vector2(1.15, 0.9), 0.08)
	tween.tween_property(sprite, "scale", Vector2.ONE, 0.1)
	await get_tree().create_timer(0.15).timeout
	if is_instance_valid(hitbox):
		hitbox.deactivate()
