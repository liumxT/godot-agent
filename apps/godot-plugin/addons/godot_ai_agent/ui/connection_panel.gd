@tool
extends PanelContainer
## 连接面板（E3-T17）。
##
## 只渲染服务暴露的只读状态；按钮仅发出信号，由生命周期转交给服务。
## 面板永不显示 session_token / client_secret。

signal connect_requested
signal disconnect_requested

const STATE_TEXT := {
	"DISCONNECTED": "未连接",
	"CONNECTING": "连接中",
	"AUTHENTICATING": "认证中",
	"CONNECTED": "已连接",
	"CLOSING": "关闭中",
	"CONNECTION_LOST": "连接中断",
	"AUTH_FAILED": "认证失败",
	"RECOVERING": "恢复中",
}

const ERROR_HINTS := {
	"CREDENTIALS_MISSING": "请先在插件设置中完成客户端登记",
	"CREDENTIALS_CORRUPT": "凭证文件损坏，请重新登记",
	"AUTH_CHALLENGE_INVALID": "客户端凭证无效，请重新登记",
	"AUTH_CLIENT_DISABLED": "客户端已被禁用，请联系管理员",
	"AUTH_RATE_LIMITED": "认证尝试过于频繁，请稍后重试",
	"BACKEND_NOT_STARTED": "请先启动本地后端",
	"BACKEND_STARTING": "后端启动中，请稍后重试",
	"BACKEND_INCOMPATIBLE": "前后端版本不兼容，请升级插件或后端",
	"BACKEND_UNREACHABLE": "后端地址不可达，请检查地址",
	"CONTRACT_INVALID": "握手响应不符合契约，请检查版本",
	"4401": "认证失败，请重新登记客户端",
	"4403": "权限不足，操作已拒绝",
	"4408": "握手超时，请检查后端状态",
	"4409": "消息过大，请减少单次数据量",
}

const SESSION_MASK_LENGTH := 12

var _state_value: Label
var _backend_value: Label
var _project_value: Label
var _session_value: Label
var _lease_value: Label
var _error_value: Label
var _hint_value: Label
var _connect_button: Button
var _disconnect_button: Button
var _ui_built := false


func _init() -> void:
	_ensure_ui()


func _ready() -> void:
	_ensure_ui()
	name = "Godot AI Agent 连接"


func _ensure_ui() -> void:
	if _ui_built:
		return
	_ui_built = true
	custom_minimum_size = Vector2(300, 0)
	var margin := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_%s" % side, 8)
	add_child(margin)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 4)
	margin.add_child(box)

	var title := Label.new()
	title.text = "连接"
	title.add_theme_font_size_override("font_size", 15)
	box.add_child(title)
	box.add_child(HSeparator.new())

	_state_value = _add_row(box, "状态")
	_backend_value = _add_row(box, "后端")
	_project_value = _add_row(box, "项目")
	_session_value = _add_row(box, "Session")
	_lease_value = _add_row(box, "租约")
	_error_value = _add_row(box, "错误")
	_hint_value = _add_row(box, "提示")

	var actions := HBoxContainer.new()
	_connect_button = Button.new()
	_connect_button.text = "连接"
	_connect_button.pressed.connect(func(): connect_requested.emit())
	_disconnect_button = Button.new()
	_disconnect_button.text = "断开"
	_disconnect_button.pressed.connect(func(): disconnect_requested.emit())
	actions.add_child(_connect_button)
	actions.add_child(_disconnect_button)
	box.add_child(actions)

	render({})


func _add_row(parent: VBoxContainer, caption: String) -> Label:
	var row := HBoxContainer.new()
	var name_label := Label.new()
	name_label.text = caption
	name_label.custom_minimum_size = Vector2(64, 0)
	name_label.modulate = Color(1, 1, 1, 0.6)
	var value_label := Label.new()
	value_label.text = "-"
	value_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	value_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(name_label)
	row.add_child(value_label)
	parent.add_child(row)
	return value_label


## 渲染服务 status() 输出；缺失字段按未连接处理。
func render(status: Dictionary) -> void:
	var connection := str(status.get("connection", "DISCONNECTED"))
	_set_label(_state_value, _state_text(connection))
	_set_label(_backend_value, str(status.get("backend_url", "-")))
	_set_label(_project_value, _project_text(status))
	_set_label(_session_value, _session_text(status))
	_set_label(_lease_value, _lease_text(status))
	_set_label(_error_value, _error_text(status))
	_set_label(_hint_value, _hint_text(status))
	var connected := connection == "CONNECTED"
	_set_button(_connect_button, not connected)
	_set_button(_disconnect_button, connection != "DISCONNECTED")


func state_text() -> String:
	return str(_state_value.text) if is_instance_valid(_state_value) else ""


func session_text() -> String:
	return str(_session_value.text) if is_instance_valid(_session_value) else ""


func lease_text() -> String:
	return str(_lease_value.text) if is_instance_valid(_lease_value) else ""


func error_text() -> String:
	return str(_error_value.text) if is_instance_valid(_error_value) else ""


func hint_text() -> String:
	return str(_hint_value.text) if is_instance_valid(_hint_value) else ""


func is_connect_enabled() -> bool:
	return is_instance_valid(_connect_button) and not _connect_button.disabled


func press_connect() -> void:
	if is_instance_valid(_connect_button):
		_connect_button.pressed.emit()


func press_disconnect() -> void:
	if is_instance_valid(_disconnect_button):
		_disconnect_button.pressed.emit()


func _state_text(connection: String) -> String:
	return str(STATE_TEXT.get(connection, connection))


func _project_text(status: Dictionary) -> String:
	var project_id := str(status.get("project_id", ""))
	if project_id.is_empty():
		return "未绑定"
	return project_id


func _session_text(status: Dictionary) -> String:
	var session_id := str(status.get("session_id", ""))
	if session_id.is_empty():
		return "无"
	return _mask_identifier(session_id)


func _lease_text(status: Dictionary) -> String:
	var lease: Dictionary = status.get("lease", {})
	if lease.is_empty():
		return "无"
	var remaining := int(status.get("lease_remaining_seconds", 0))
	return "%s · %ds · fencing %d" % [
		str(lease.get("status", "-")),
		remaining,
		int(lease.get("fencing_token", 0)),
	]


func _error_text(status: Dictionary) -> String:
	var code := str(status.get("error_code", ""))
	if code.is_empty():
		return ""
	return code


func _hint_text(status: Dictionary) -> String:
	var code := str(status.get("error_code", ""))
	if code.is_empty():
		return ""
	var message := str(status.get("message", ""))
	var hint := str(ERROR_HINTS.get(code, ""))
	if hint.is_empty():
		return message
	if message.is_empty():
		return hint
	return "%s（%s）" % [hint, message]


## 只显示标识前缀，避免面板泄露完整 Session。
func _mask_identifier(value: String) -> String:
	if value.length() <= SESSION_MASK_LENGTH:
		return value
	return value.substr(0, SESSION_MASK_LENGTH) + "…"


func _set_label(label: Label, text: String) -> void:
	if is_instance_valid(label):
		label.text = text


func _set_button(button: Button, enabled: bool) -> void:
	if is_instance_valid(button):
		button.disabled = not enabled
