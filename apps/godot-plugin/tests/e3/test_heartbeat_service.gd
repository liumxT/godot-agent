@tool
extends "res://tests/test_case.gd"
## 心跳服务测试（E3-T09 客户端侧）。

const HeartbeatService := preload("res://addons/godot_ai_agent/services/heartbeat_service.gd")
const PluginContext := preload("res://addons/godot_ai_agent/core/plugin_context.gd")

const SESSION_ID := "ses_000000000001"
const PROJECT_ID := "prj_abcdefghijkl"
const EDITOR_INSTANCE := "edi_0123456789ab"


class FakeSession extends RefCounted:
	signal connection_changed(state: String, detail: String)
	signal response_received(action: String, response: Dictionary)
	signal event_received(event: Dictionary)

	var connected := false
	var requests: Array = []
	var data := {
		"session_id": SESSION_ID,
		"project_id": PROJECT_ID,
		"editor_instance_id": EDITOR_INSTANCE,
	}
	var counter := 0

	func is_session_connected() -> bool:
		return connected

	func session_data() -> Dictionary:
		return data.duplicate(true)

	func send_request(action: String, payload: Dictionary, delivery: String = "PERSISTENT") -> String:
		if not connected:
			return ""
		counter += 1
		var request_id := "req_fake%04d" % counter
		requests.append({
			"request_id": request_id,
			"action": action,
			"payload": payload.duplicate(true),
			"delivery": delivery,
		})
		return request_id

	func drop_pending_requests(_action: String) -> void:
		pass

	func respond(action: String, response: Dictionary) -> void:
		response_received.emit(action, response)


func _init() -> void:
	suite_name = "t09_heartbeat"


func _make_service(interval: float = 10.0, timeout: float = 30.0, max_missed: int = 3):
	var ctx = PluginContext.new(null, "0.1.0", "4.5.1")
	ctx.set_config("heartbeat_interval_seconds", interval)
	ctx.set_config("heartbeat_timeout_seconds", timeout)
	ctx.set_config("heartbeat_max_missed", max_missed)
	var service = HeartbeatService.new()
	assert_true(service.initialize(ctx))
	assert_true(service.start())
	return service


func _success_response(resync: bool = false) -> Dictionary:
	return {
		"protocol_version": "1.0",
		"request_id": "req_fake0001",
		"success": true,
		"data": {
			"server_time": Time.get_datetime_string_from_unix_time(
				int(Time.get_unix_time_from_system())
			) + "Z",
			"resync_required": resync,
			"lease": {"lease_id": "lea_000000000001", "status": "ACTIVE", "fencing_token": 1},
		},
		"error": null,
	}


## T09-UT-001：连接建立后立即发送心跳，响应后恢复 HEALTHY。
func test_heartbeat_sends_on_connect_and_recovers() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	var done: Array = []
	var resyncs: Array = []
	service.heartbeat_done.connect(func(sequence): done.append(sequence))
	service.resync_required.connect(func(): resyncs.append(true))
	service.attach_session(session)

	session.connected = true
	session.connection_changed.emit("CONNECTED", "")
	assert_eq(session.requests.size(), 1)
	assert_eq(str(session.requests[0]["action"]), "session.heartbeat")
	assert_eq(str(session.requests[0]["delivery"]), "EPHEMERAL")
	assert_eq(int(session.requests[0]["payload"]["sequence"]), 1)
	assert_true(str(session.requests[0]["payload"]["state_digest"]).length() > 0)

	session.respond("session.heartbeat", _success_response(true))
	assert_eq(done.size(), 1)
	assert_eq(resyncs.size(), 1)
	assert_eq(str(service.status()["health"]), "HEALTHY")
	assert_true(service.is_healthy())
	assert_eq(service.sequence(), 1)
	service.stop("test")


## T09-UT-002：连续 3 次无响应进入 LOST 并广播 connection_lost。
func test_heartbeat_timeout_marks_lost() -> void:
	var service = _make_service(0.1, 0.05, 3)
	var session := FakeSession.new()
	session.connected = true
	var losses: Array = []
	service.connection_lost.connect(func(detail): losses.append(detail))
	service.attach_session(session)
	assert_eq(session.requests.size(), 1)

	service.tick(0.06)
	service.tick(0.06)
	service.tick(0.06)

	assert_eq(losses.size(), 1)
	assert_eq(str(service.status()["health"]), "LOST")
	assert_false(service.is_healthy())
	assert_eq(int(service.status()["missed"]), 3)
	service.stop("test")


## T09-UT-003：非心跳响应不改变心跳状态。
func test_other_responses_are_ignored() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	session.connected = true
	service.attach_session(session)

	session.respond("editor.snapshot", {"success": true, "data": {}, "error": null})
	assert_eq(str(service.status()["health"]), "HEALTHY")
	assert_eq(int(service.status()["missed"]), 0)
	service.stop("test")
