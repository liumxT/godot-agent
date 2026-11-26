extends Control
## 暂停菜单：仅修改流程状态，不直接操作场景树。

var ui_id := "pause_menu"

@onready var resume_button: Button = $Panel/ResumeButton
@onready var menu_button: Button = $Panel/MainMenuButton


func _ready() -> void:
	add_to_group("flow_ui")
	resume_button.pressed.connect(_on_resume_pressed)
	menu_button.pressed.connect(_on_menu_pressed)
	set_active(false)


func set_active(value: bool) -> void:
	visible = value
	if value:
		resume_button.grab_focus()


func _on_resume_pressed() -> void:
	GameFlowManager.resume_game()


func _on_menu_pressed() -> void:
	GameFlowManager.to_menu()
