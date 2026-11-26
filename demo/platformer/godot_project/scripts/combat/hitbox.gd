extends Area2D
## 攻击判定：只统计处于 hurtbox 组的对象，同一目标每次攻击最多命中一次。

@export var damage: int = 1

var source_id: String = "unknown"
var active: bool = false

var _hit_targets: Dictionary = {}


func _ready() -> void:
	monitoring = false
	monitorable = false
	area_entered.connect(_on_area_entered)


func activate() -> void:
	_hit_targets.clear()
	active = true
	monitoring = true
	monitorable = true


func deactivate() -> void:
	active = false
	# 可能由 area_entered 信号链间接触发，物理状态必须延迟切换
	set_deferred("monitoring", false)
	set_deferred("monitorable", false)


func _on_area_entered(area: Area2D) -> void:
	if not active:
		return
	if not area.is_in_group("hurtbox"):
		return
	if area.get_parent() == get_parent():
		return
	var key := area.get_instance_id()
	if _hit_targets.has(key):
		return
	if not area.has_method("receive_damage"):
		return
	var accepted = area.call(
		"receive_damage",
		{
			"amount": damage,
			"source_id": source_id,
			"source_position": global_position,
		}
	)
	if accepted:
		_hit_targets[key] = true
