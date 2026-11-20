@tool
extends "res://tests/test_case.gd"
## 快照服务测试（E3-T11 客户端侧）。

const SnapshotService := preload("res://addons/godot_ai_agent/services/snapshot_service.gd")
const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")
const PluginContext := preload("res://addons/godot_ai_agent/core/plugin_context.gd")

const SESSION_ID := "ses_000000000001"
const PROJECT_ID := "prj_abcdefghijkl"
const EDITOR_INSTANCE := "edi_0123456789ab"


class FakeSession extends RefCounted:
	signal response_received(action: String, response: Dictionary)

	var connected := true
	var requests: Array = []
	var counter := 0

	func is_session_connected() -> bool:
		return connected

	func session_data() -> Dictionary:
		return {
			"session_id": SESSION_ID,
			"project_id": PROJECT_ID,
			"editor_instance_id": EDITOR_INSTANCE,
		}

	func send_request(action: String, payload: Dictionary, delivery: String = "PERSISTENT") -> String:
		counter += 1
		var request_id := "req_fake%04d" % counter
		requests.append({
			"request_id": request_id,
			"action": action,
			"payload": payload.duplicate(true),
			"delivery": delivery,
		})
		return request_id

	func respond(action: String, response: Dictionary) -> void:
		response_received.emit(action, response)


class FakeEventSync extends RefCounted:
	var sequence := 0

	func last_sequence() -> int:
		return sequence


class FakeStateProvider extends RefCounted:
	func collect() -> Dictionary:
		return {
			"editor_status": "READY",
			"project_status": "READY",
			"active_scene": "res://scenes/main.tscn",
			"current_selection": ["/root/Main"],
			"unsaved_resources": [{"path": "res://scenes/main.tscn", "resource_type": "scene"}],
			"run_status": "RUNNING",
			"import_status": "IMPORTING",
		}


func _init() -> void:
	suite_name = "t11_snapshot"


func _make_service():
	var ctx = PluginContext.new(null, "0.1.0", "4.5.1")
	ctx.set_config("editor_status_override", "READY")
	ctx.set_config("project_status_override", "READY")
	ctx.set_config("run_status_override", "STOPPED")
	var service = SnapshotService.new()
	assert_true(service.initialize(ctx))
	assert_true(service.start())
	return service


func _response(snapshot: Dictionary) -> Dictionary:
	return {
		"protocol_version": "1.0",
		"request_id": "req_fake0001",
		"success": true,
		"data": {"kind": "snapshot", "snapshot": snapshot},
		"error": null,
	}


## T11-UT-001：采集结果符合快照契约，版本递增且关联事件进度。
func test_capture_builds_valid_snapshot() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	var events := FakeEventSync.new()
	events.sequence = 7
	service.attach_session(session)
	service.attach_event_sync(events)

	var first: Dictionary = service.capture()
	assert_false(first.is_empty())
	assert_eq(Validator.validate_bridge_snapshot(first), [])
	assert_eq(int(first["snapshot_version"]), 1)
	assert_eq(int(first["last_event_sequence"]), 7)
	assert_eq(str(first["session_id"]), SESSION_ID)
	assert_eq(str(first["editor_instance_id"]), EDITOR_INSTANCE)
	assert_true(str(first["snapshot_id"]).begins_with("snp_"))

	var second: Dictionary = service.capture()
	assert_eq(int(second["snapshot_version"]), 2)
	assert_true(str(second["snapshot_id"]) != str(first["snapshot_id"]))
	service.stop("test")


## T11-UT-002：submit 提交快照，成功后返回并缓存服务端版本。
func test_submit_sends_snapshot_and_caches() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	var stored: Array = []
	service.snapshot_stored.connect(func(snapshot): stored.append(snapshot))
	service.attach_session(session)

	var request_id := service.submit()
	assert_true(request_id.length() > 0)
	assert_eq(session.requests.size(), 1)
	assert_eq(str(session.requests[0]["action"]), "editor.snapshot")
	var payload: Dictionary = session.requests[0]["payload"]
	assert_eq(Validator.validate_bridge_snapshot(payload), [])

	session.respond("editor.snapshot", _response(payload))
	assert_eq(stored.size(), 1)
	assert_eq(str(service.latest_snapshot()["snapshot_id"]), str(payload["snapshot_id"]))
	service.stop("test")


## T11-UT-003：request_latest 只发送空 payload 并接收服务端快照。
func test_request_latest_receives_snapshot() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	var received: Array = []
	service.snapshot_received.connect(func(snapshot): received.append(snapshot))
	service.attach_session(session)

	assert_true(service.request_latest().length() > 0)
	assert_eq(session.requests[0]["payload"], {})
	var snapshot: Dictionary = service.capture()
	session.respond("editor.snapshot", _response(snapshot))

	assert_eq(received.size(), 1)
	assert_eq(str(service.latest_snapshot()["snapshot_id"]), str(snapshot["snapshot_id"]))
	service.stop("test")


## T11-UT-004：未建立会话时拒绝采集并报 SESSION_UNAVAILABLE。
func test_capture_without_session_fails() -> void:
	var service = _make_service()
	var errors: Array = []
	service.snapshot_failed.connect(func(code, _message): errors.append(code))

	assert_true(service.capture().is_empty())
	assert_eq(errors, ["SESSION_UNAVAILABLE"])
	service.stop("test")


## T15 集成：快照复用状态采集服务，未保存资源不再丢失。
func test_capture_uses_state_provider() -> void:
	var service = _make_service()
	service.attach_session(FakeSession.new())
	service.attach_state_provider(FakeStateProvider.new())

	var snapshot: Dictionary = service.capture()
	assert_eq(Validator.validate_bridge_snapshot(snapshot), [])
	assert_eq(str(snapshot["active_scene"]), "res://scenes/main.tscn")
	assert_eq(str(snapshot["run_status"]), "RUNNING")
	assert_eq(str(snapshot["import_status"]), "IMPORTING")
	assert_eq((snapshot["unsaved_resources"] as Array).size(), 1)
	service.stop("test")
