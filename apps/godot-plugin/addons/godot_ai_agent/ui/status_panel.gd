@tool
extends PanelContainer
## 插件状态面板：仅展示状态，不执行任何项目操作。


var _plugin_status: Label
var _backend_status: Label
var _version_status: Label


func _ready() -> void:
	name = "Godot AI Agent"
	custom_minimum_size = Vector2(260, 0)
	_build_ui()


func _build_ui() -> void:
	var margin := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_%s" % side, 8)
	add_child(margin)

	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 4)
	margin.add_child(box)

	var title := Label.new()
	title.text = "Godot AI Agent"
	title.add_theme_font_size_override("font_size", 15)
	box.add_child(title)

	box.add_child(HSeparator.new())

	_plugin_status = _add_row(box, "插件")
	_backend_status = _add_row(box, "后端")
	_version_status = _add_row(box, "Godot")


func _add_row(parent: VBoxContainer, caption: String) -> Label:
	var row := HBoxContainer.new()
	var name_label := Label.new()
	name_label.text = caption
	name_label.custom_minimum_size = Vector2(64, 0)
	name_label.modulate = Color(1, 1, 1, 0.6)
	var value_label := Label.new()
	value_label.text = "-"
	row.add_child(name_label)
	row.add_child(value_label)
	parent.add_child(row)
	return value_label


func set_plugin_status(text: String) -> void:
	if is_instance_valid(_plugin_status):
		_plugin_status.text = text


func set_backend_status(text: String) -> void:
	if is_instance_valid(_backend_status):
		_backend_status.text = text


func set_godot_version(text: String) -> void:
	if is_instance_valid(_version_status):
		_version_status.text = text
