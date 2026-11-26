extends CharacterBody2D
## 敌人基类：生命、受击、死亡与 Hitbox 初始化。

@export var max_health: int = 2
@export var move_speed: float = 60.0
@export var attack_damage: int = 1

var health: int = 2
var dead: bool = false

@onready var sprite: Sprite2D = $Sprite2D
@onready var hurtbox: Area2D = $Hurtbox
@onready var hitbox: Variant = $Hitbox


func _ready() -> void:
	add_to_group("enemy")
	health = max_health
	hitbox.damage = attack_damage
	hitbox.source_id = str(name)


func _physics_process(delta: float) -> void:
	if dead:
		return
	velocity.y = minf(velocity.y + 1200.0 * delta, 900.0)


func take_damage(amount: int, _source_position: Vector2 = Vector2.ZERO) -> bool:
	if dead or amount <= 0:
		return false
	health = maxi(health - amount, 0)
	_flash()
	if health == 0:
		die()
	return true


func die() -> void:
	if dead:
		return
	dead = true
	hurtbox.set_deferred("monitorable", false)
	hitbox.deactivate()
	EventBus.enemy_defeated.emit()
	var tween := create_tween()
	tween.set_parallel(true)
	tween.tween_property(sprite, "modulate:a", 0.0, 0.3)
	tween.tween_property(sprite, "scale", Vector2(0.2, 0.2), 0.3)
	await get_tree().create_timer(0.35).timeout
	queue_free()


func _flash() -> void:
	var tween := create_tween()
	tween.tween_property(sprite, "modulate", Color(1, 0.4, 0.4), 0.08)
	tween.tween_property(sprite, "modulate", Color.WHITE, 0.12)
