extends Area2D
## 关卡终点：玩家进入后进入胜利结算。


func _ready() -> void:
	add_to_group("goal")
	body_entered.connect(_on_body_entered)


func _on_body_entered(body: Node2D) -> void:
	if body.is_in_group("player"):
		GameFlowManager.on_goal_reached()
