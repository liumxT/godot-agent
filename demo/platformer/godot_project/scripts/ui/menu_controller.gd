extends Control
## 主菜单控制器。

var ui_id := "main_menu"

@onready var start_button: Button = $Menu/StartButton
@onready var quit_button: Button = $Menu/QuitButton
@onready var title_label: Label = $Menu/TitleLabel


func _ready() -> void:
	add_to_group("flow_ui")
	start_button.pressed.connect(_on_start_pressed)
	quit_button.pressed.connect(_on_quit_pressed)
	set_active(false)


func set_active(value: bool) -> void:
	visible = value
	if value:
		start_button.grab_focus()


func _on_start_pressed() -> void:
	GameFlowManager.start_game()


func _on_quit_pressed() -> void:
	get_tree().quit()
