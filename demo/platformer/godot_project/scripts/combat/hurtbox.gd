extends Area2D
## 受击判定：把伤害转交给拥有者（玩家或敌人）。


func receive_damage(data: Dictionary) -> bool:
	var target := get_parent()
	if target == null or not target.has_method("take_damage"):
		return false
	return target.call(
		"take_damage",
		int(data.get("amount", 1)),
		data.get("source_position", Vector2.ZERO)
	)
