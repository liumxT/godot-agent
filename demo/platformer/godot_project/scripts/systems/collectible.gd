extends Area2D
## 收集物：先置 collected 再计分，避免重复触发。

@export var value: int = 10
@export var kind: String = "coin"

var collected: bool = false

@onready var sprite: Sprite2D = $Sprite2D


func _ready() -> void:
	add_to_group("collectible")
	if kind == "gem":
		sprite.texture = load("res://assets/ui/gem.svg")
	body_entered.connect(_on_body_entered)
	_bob()


func _on_body_entered(body: Node2D) -> void:
	if collected or not body.is_in_group("player"):
		return
	collected = true
	set_deferred("monitoring", false)
	ScoreManager.add_score(value)
	EventBus.collectible_collected.emit(value)
	_play_pickup()


func _bob() -> void:
	var tween := create_tween()
	tween.set_loops()
	tween.tween_property(sprite, "position:y", -3.0, 0.6)
	tween.tween_property(sprite, "position:y", 0.0, 0.6)


func _play_pickup() -> void:
	var tween := create_tween()
	tween.set_parallel(true)
	tween.tween_property(sprite, "scale", Vector2(1.6, 1.6), 0.15)
	tween.tween_property(sprite, "modulate:a", 0.0, 0.15)
	await get_tree().create_timer(0.16).timeout
	queue_free()
