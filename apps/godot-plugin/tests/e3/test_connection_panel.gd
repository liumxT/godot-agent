@tool
extends "res://tests/test_case.gd"
## 连接面板与生命周期集成测试（E3-T17）。

const ConnectionPanel := preload("res://addons/godot_ai_agent/ui/connection_panel.gd")
const PluginLifecycle := preload("res://addons/godot_ai_agent/core/plugin_lifecycle.gd")
const CredentialsStore := preload("res://addons/godot_ai_agent/utilities/credentials_store.gd")


class FakeHost:
	var docks: Array = []

	func add_control_to_dock(_slot: int, control: Control) -> void:
		docks.append(control)

	func remove_control_from_docks(control: Control) -> void:
		docks.erase(control)


func _init() -> void:
	suite_name = "t17_connection_panel"


func _status(overrides: Dictionary = {}) -> Dictionary:
	var status := {
		"name": "editor_session_service",
		"state": "RUNNING",
		"error_code": "",
		"detail": "",
		"connection": "CONNECTED",
		"backend_url": "ws://127.0.0.1:8765/api/v1/ws/editor",
		"session_id": "ses_000000000001",
		"project_id": "prj_abcdefghijkl",
		"editor_instance_id": "edi_0123456789ab",
		"lease": {
			"lease_id": "lea_000000000001",
			"session_id": "ses_000000000001",
			"project_id": "prj_abcdefghijkl",
			"fencing_token": 3,
			"status": "ACTIVE",
			"issued_at": "2026-11-20T09:00:00Z",
			"renewed_at": null,
			"expires_at": "2026-11-20T09:00:45Z",
			"revoked_at": null,
		},
		"lease_remaining_seconds": 42,
		"message": "",
	}
	for key in overrides:
		status[key] = overrides[key]
	return status


## T17-UT-001：已连接时显示状态、项目、租约，且不泄露 Token。
func test_connected_state_renders() -> void:
	var panel = ConnectionPanel.new()
	panel.render(_status())

	assert_eq(panel.state_text(), "已连接")
	assert_eq(panel.session_text().substr(0, 4), "ses_")
	assert_false(panel.session_text().contains("gds_"))
	assert_true(panel.lease_text().contains("ACTIVE"))
	assert_true(panel.lease_text().contains("fencing 3"))
	assert_eq(panel.error_text(), "")
	assert_false(panel.is_connect_enabled())
	panel.free()


## T17-UT-002：错误码映射为中文提示，连接按钮可用。
func test_error_state_renders_hint() -> void:
	var panel = ConnectionPanel.new()
	panel.render(_status({
		"connection": "DISCONNECTED",
		"session_id": "",
		"project_id": "",
		"lease": {},
		"lease_remaining_seconds": 0,
		"error_code": "CREDENTIALS_MISSING",
		"message": "缺少客户端凭证",
	}))
	assert_eq(panel.state_text(), "未连接")
	assert_eq(panel.error_text(), "CREDENTIALS_MISSING")
	assert_true(panel.hint_text().contains("登记"))
	assert_true(panel.is_connect_enabled())
	panel.free()


## T17-UT-003：按钮只发信号，不直接访问服务。
func test_buttons_emit_signals() -> void:
	var panel = ConnectionPanel.new()
	var events: Array = []
	panel.connect_requested.connect(func(): events.append("connect"))
	panel.disconnect_requested.connect(func(): events.append("disconnect"))

	panel.press_connect()
	panel.press_disconnect()

	assert_eq(events.size(), 2)
	assert_eq(str(events[0]), "connect")
	assert_eq(str(events[1]), "disconnect")
	panel.free()


## T17-IT-001：生命周期启用默认服务时注册连接面板，关闭时释放。
func test_lifecycle_registers_and_releases_panel() -> void:
	CredentialsStore.new().clear()
	var host := FakeHost.new()
	var lifecycle = PluginLifecycle.new()

	assert_true(lifecycle.enable(host, 3, "0.1.0", true))
	assert_eq(host.docks.size(), 2)
	var panel = lifecycle.get("_connection_panel")
	assert_not_null(panel)
	assert_eq(str(panel.call("state_text")), "未连接")
	assert_true(str(panel.call("hint_text")).contains("登记"))

	lifecycle.disable("test")
	assert_eq(host.docks.size(), 0)
