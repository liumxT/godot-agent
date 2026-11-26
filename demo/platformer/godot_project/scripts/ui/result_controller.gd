extends Control
## 结算界面：区分胜利与失败，展示最终分数与最佳分数。

var ui_id := "result_screen"

@onready var title_label: Label = $Panel/TitleLabel
@onready var score_label: Label = $Panel/ScoreLabel
@onready var best_label: Label = $Panel/BestLabel
@onready var retry_button: Button = $Panel/RetryButton
@onready var menu_button: Button = $Panel/MainMenuButton


func _ready() -> void:
	add_to_group("flow_ui")
	retry_button.pressed.connect(_on_retry_pressed)
	menu_button.pressed.connect(_on_menu_pressed)
	set_active(false)


func set_active(value: bool) -> void:
	visible = value
	if not value:
		return
	var victory := GameFlowManager.state == GameFlowManager.State.VICTORY
	title_label.text = "VICTORY" if victory else "GAME OVER"
	title_label.modulate = Color(0.55, 0.9, 0.6) if victory else Color(0.95, 0.5, 0.45)
	score_label.text = "SCORE %d" % GameFlowManager.last_score
	best_label.text = "BEST %d" % ScoreManager.best_score
	retry_button.grab_focus()


func _on_retry_pressed() -> void:
	GameFlowManager.restart_level()


func _on_menu_pressed() -> void:
	GameFlowManager.to_menu()
