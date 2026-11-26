extends CharacterBody2D
## 玩家控制器：移动、跳跃、朝向与受击表现。
## 攻击委托给 Combat 节点，生命委托给 Health 节点，流程委托给 GameFlowManager。

@export var config: PlayerConfig

var _jump_buffer_left: float = 0.0
var _coyote_left: float = 0.0
var _facing: int = 1
var _dead: bool = false

@onready var sprite: Sprite2D = $Sprite2D
@onready var health: Variant = $Health
@onready var combat: Variant = $Combat
@onready var hurtbox: Area2D = $Hurtbox
@onready var hitbox: Variant = $Hitbox


func _ready() -> void:
	add_to_group("player")
	if config == null:
		config = PlayerConfig.new()
	health.setup(config.max_health, config.invulnerability)
	health.health_changed.connect(_on_health_changed)
	health.died.connect(_on_died)
	combat.setup(self, config)
	health.health_changed.emit(health.current_health, health.max_health)


func _physics_process(delta: float) -> void:
	if _dead:
		velocity.y = minf(velocity.y + config.gravity * delta, config.max_fall_speed)
		move_and_slide()
		return

	_update_timers(delta)
	_handle_attack_input()
	_handle_horizontal(delta)
	_handle_jump()
	_apply_gravity(delta)
	move_and_slide()


func _update_timers(delta: float) -> void:
	if Input.is_action_just_pressed("jump"):
		_jump_buffer_left = config.jump_buffer
	else:
		_jump_buffer_left = maxf(_jump_buffer_left - delta, 0.0)
	if is_on_floor():
		_coyote_left = config.coyote_time
	else:
		_coyote_left = maxf(_coyote_left - delta, 0.0)


func _handle_attack_input() -> void:
	if Input.is_action_just_pressed("attack"):
		combat.try_attack(_facing)


func _handle_horizontal(delta: float) -> void:
	var direction := Input.get_axis("move_left", "move_right")
	if direction != 0.0:
		_facing = 1 if direction > 0.0 else -1
		sprite.flip_h = _facing < 0
	var control := 1.0 if is_on_floor() else config.air_control
	var rate := config.acceleration if direction != 0.0 else config.friction
	velocity.x = move_toward(velocity.x, direction * config.max_speed, rate * control * delta)


func _handle_jump() -> void:
	if _jump_buffer_left > 0.0 and _coyote_left > 0.0:
		velocity.y = config.jump_velocity
		_jump_buffer_left = 0.0
		_coyote_left = 0.0
		EventBus.player_jumped.emit()
		_spawn_jump_dust()


func _apply_gravity(delta: float) -> void:
	if not is_on_floor():
		velocity.y = minf(velocity.y + config.gravity * delta, config.max_fall_speed)


func take_damage(amount: int, source_position: Vector2 = Vector2.ZERO) -> bool:
	if _dead:
		return false
	if not health.take_damage(amount):
		return false
	var away := 1.0
	if source_position != Vector2.ZERO:
		away = -1.0 if source_position.x > global_position.x else 1.0
	velocity.x = config.knockback * away
	velocity.y = minf(velocity.y, -120.0)
	EventBus.player_damaged.emit(amount)
	_flash()
	return true


func is_dead() -> bool:
	return _dead


func _on_health_changed(current: int, maximum: int) -> void:
	EventBus.health_changed.emit(current, maximum)


func _on_died() -> void:
	if _dead:
		return
	_dead = true
	hurtbox.set_deferred("monitorable", false)
	hitbox.deactivate()
	EventBus.player_died.emit()
	var tween := create_tween()
	tween.tween_property(sprite, "modulate", Color(1, 0.4, 0.4, 0.2), 0.4)
	tween.tween_property(sprite, "rotation_degrees", -90.0, 0.25)
	await get_tree().create_timer(0.6).timeout
	GameFlowManager.on_player_died()


func _flash() -> void:
	var tween := create_tween()
	tween.tween_property(sprite, "modulate", Color(1, 0.5, 0.5), 0.08)
	tween.tween_property(sprite, "modulate", Color.WHITE, 0.12)


func _spawn_jump_dust() -> void:
	var dust := ColorRect.new()
	dust.color = Color(0.85, 0.85, 0.8, 0.7)
	dust.size = Vector2(14, 4)
	dust.position = global_position + Vector2(-7, 12)
	get_parent().add_child(dust)
	var tween := create_tween()
	tween.tween_property(dust, "modulate:a", 0.0, 0.25)
	tween.tween_callback(dust.queue_free)
