@tool
extends "res://tests/test_case.gd"
## 编辑器状态采集测试（E3-T15 客户端侧）。

const EditorStateProvider := preload(
	"res://addons/godot_ai_agent/state/editor_state_provider.gd"
)
const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")
const PluginContext := preload("res://addons/godot_ai_agent/core/plugin_context.gd")


class FakeSession extends RefCounted:
	signal session_established(session: Dictionary)

	var connected := true
	var requests: Array = []
	var counter := 0

	func is_session_connected() -> bool:
		return connected

	func send_request(action: String, payload: Dictionary, delivery: String = "PERSISTENT") -> String:
		counter += 1
		var request_id := "req_state%04d" % counter
		requests.append({
			"request_id": request_id,
			"action": action,
			"payload": payload.duplicate(true),
			"delivery": delivery,
		})
		return request_id


class FakeRegistry extends RefCounted:
	var session: Object = null

	func get_service(name: String) -> Object:
		if name == "editor_session_service":
			return session
		return null


func _init() -> void:
	suite_name = "t15_editor_state"


func _make_service(session: Object = null):
	var ctx = PluginContext.new(null, "0.1.0", "4.5.1")
	var registry := FakeRegistry.new()
	registry.session = session if session != null else FakeSession.new()
	ctx.set_config("service_registry", registry)
	var service = EditorStateProvider.new()
	assert_true(service.initialize(ctx))
	assert_true(service.start())
	return service


func _state(overrides: Dictionary = {}) -> Dictionary:
	var state := {
		"editor_status": "READY",
		"project_status": "READY",
		"active_scene": "res://scenes/main.tscn",
		"current_selection": ["/root/Main/Player"],
		"unsaved_resources": [],
		"run_status": "STOPPED",
		"import_status": "IDLE",
	}
	state.merge(overrides, true)
	return state


## T15-UT-001：采集结果覆盖 7 个字段且符合契约。
func test_collect_builds_valid_state() -> void:
	var service = _make_service()
	service.context.set_config("state_override", _state({
		"unsaved_resources": [{"path": "res://scenes/main.tscn", "resource_type": "scene"}],
	}))

	var state: Dictionary = service.collect()
	assert_eq(state.keys().size(), 7, "字段集合固定")
	assert_eq(Validator.validate_bridge_editor_state(state), [])
	assert_eq(str(state["active_scene"]), "res://scenes/main.tscn")
	assert_eq(state["current_selection"], ["/root/Main/Player"])
	assert_eq((state["unsaved_resources"] as Array).size(), 1)
	service.stop("test")


## T15-UT-002：diff 只返回变化字段，顺序与固定字段表一致。
func test_diff_reports_changed_fields_only() -> void:
	var previous := _state()
	var current := _state({
		"current_selection": ["/root/Main/Enemy"],
		"run_status": "RUNNING",
	})
	var changed: Array = EditorStateProvider.changed_fields(previous, current)
	assert_eq(changed, ["current_selection", "run_status"])
	assert_eq(EditorStateProvider.changed_fields(previous, previous), [])
	# 数组与嵌套字典按值比较，不应误报。
	var copy := previous.duplicate(true)
	assert_eq(EditorStateProvider.changed_fields(previous, copy), [])


## T15-UT-003：节流生效；首次全量 PERSISTENT，仅选择变化走 EPHEMERAL。
func test_report_throttles_and_uses_ephemeral_for_selection() -> void:
	var service = _make_service()
	var registry: FakeRegistry = service.context.get_config("service_registry")
	var session: FakeSession = registry.session
	service.context.set_config("state_override", _state())

	service.tick(1.0)
	assert_eq(session.requests.size(), 1, "首次状态应上报")
	var first: Dictionary = session.requests[0]
	assert_eq(str(first["action"]), "editor.state.report")
	assert_eq(str(first["delivery"]), "PERSISTENT")
	assert_eq(first["payload"]["changed"].size(), 7)
	assert_eq(Validator.validate_bridge_editor_state(
		_payload_state(first["payload"])
	), [])

	# 未变化：下一周期不再上报。
	service.tick(1.0)
	assert_eq(session.requests.size(), 1, "相同状态不应重复上报")

	# 仅选中变化：下一个周期以 EPHEMERAL 上报。
	service.context.set_config("state_override", _state({
		"current_selection": ["/root/Main/Enemy"],
	}))
	service.tick(1.0)
	assert_eq(session.requests.size(), 2)
	var second: Dictionary = session.requests[1]
	assert_eq(str(second["delivery"]), "EPHEMERAL")
	assert_eq(second["payload"]["changed"], ["current_selection"])
	service.stop("test")


## T15-UT-004：未保存资源过滤非法项，无编辑器时安全回退。
func test_unsaved_filter_and_safe_fallback() -> void:
	var service = _make_service()
	service.context.set_config("state_override", _state({
		"unsaved_resources": [
			{"path": "res://scenes/main.tscn", "resource_type": "scene"},
			{"path": "scenes/broken.tscn", "resource_type": "scene"},
			{"path": "res://scenes/empty.tscn", "resource_type": ""},
			{"path": "user://settings.cfg", "resource_type": "resource"},
		],
	}))
	var state: Dictionary = service.collect()
	assert_eq((state["unsaved_resources"] as Array).size(), 2, "只保留合法资源路径")
	assert_eq(Validator.validate_bridge_editor_state(state), [])
	service.stop("test")

	var fallback = _make_service()
	fallback.context.set_config("state_override", {})
	var live: Dictionary = fallback.collect()
	assert_eq(Validator.validate_bridge_editor_state(live), [])
	assert_eq(str(live["editor_status"]), "UNKNOWN", "无编辑器接口时回退 UNKNOWN")
	assert_eq(str(live["run_status"]), "STOPPED")
	assert_eq(str(live["import_status"]), "IDLE")
	assert_null(live["active_scene"])
	assert_eq(live["current_selection"], [])
	fallback.stop("test")


## 会话未连接时不产生上报。
func test_report_requires_connected_session() -> void:
	var session := FakeSession.new()
	session.connected = false
	var service = _make_service(session)
	service.context.set_config("state_override", _state())
	service.tick(1.0)
	assert_eq(session.requests.size(), 0)
	assert_eq(service.report(), "")
	service.stop("test")


func _payload_state(payload: Dictionary) -> Dictionary:
	var state := payload.duplicate(true)
	state.erase("changed")
	return state
