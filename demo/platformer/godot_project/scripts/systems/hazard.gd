extends Area2D
## 陷阱：真实碰撞体，接触对玩家造成伤害。

@export var damage: int = 1


func _ready() -> void:
	add_to_group("hazard")
	body_entered.connect(_on_body_entered)


func _on_body_entered(body: Node2D) -> void:
	if not body.is_in_group("player"):
		return
	if body.has_method("take_damage"):
		body.call("take_damage", damage, global_position)
