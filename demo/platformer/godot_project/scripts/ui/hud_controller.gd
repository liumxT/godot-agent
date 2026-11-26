extends Control
## HUD 控制器：只消费状态信号，不持有权威数据。

var ui_id := "hud"

@onready var health_label: Label = $HealthLabel
@onready var score_label: Label = $ScoreLabel


func _ready() -> void:
	add_to_group("flow_ui")
	EventBus.health_changed.connect(_on_health_changed)
	EventBus.score_changed.connect(_on_score_changed)
	EventBus.best_score_changed.connect(_on_best_score_changed)
	set_active(false)
	_refresh(3, 3, ScoreManager.score)


func set_active(value: bool) -> void:
	visible = value


func _on_health_changed(current: int, maximum: int) -> void:
	_refresh(current, maximum, ScoreManager.score)


func _on_score_changed(score: int) -> void:
	score_label.text = "SCORE %d" % score


func _on_best_score_changed(best: int) -> void:
	score_label.text = "SCORE %d  BEST %d" % [ScoreManager.score, best]


func _refresh(current: int, maximum: int, score: int) -> void:
	health_label.text = "HP %s" % "♥".repeat(maxi(current, 0)) + "·".repeat(maxi(maximum - current, 0))
	score_label.text = "SCORE %d  BEST %d" % [score, ScoreManager.best_score]
