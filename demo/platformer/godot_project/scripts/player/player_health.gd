extends Node
## 生命组件：权威生命值、无敌帧与死亡判定。

signal health_changed(current: int, maximum: int)
signal damaged(amount: int)
signal died

var current_health: int = 3
var max_health: int = 3
var invulnerability: float = 1.0
var is_dead: bool = false

var _invulnerable_left: float = 0.0


func setup(maximum: int, invulnerability_seconds: float) -> void:
	max_health = maxi(maximum, 1)
	current_health = max_health
	invulnerability = maxf(invulnerability_seconds, 0.0)
	is_dead = false
	health_changed.emit(current_health, max_health)


func _process(delta: float) -> void:
	if _invulnerable_left > 0.0:
		_invulnerable_left = maxf(_invulnerable_left - delta, 0.0)


func is_invulnerable() -> bool:
	return _invulnerable_left > 0.0


func take_damage(amount: int) -> bool:
	if is_dead or amount <= 0 or is_invulnerable():
		return false
	current_health = maxi(current_health - amount, 0)
	_invulnerable_left = invulnerability
	health_changed.emit(current_health, max_health)
	damaged.emit(amount)
	if current_health == 0:
		is_dead = true
		died.emit()
	return true


func heal(amount: int) -> void:
	if is_dead:
		return
	current_health = mini(current_health + amount, max_health)
	health_changed.emit(current_health, max_health)
