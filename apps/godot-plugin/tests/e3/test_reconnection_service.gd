@tool
extends "res://tests/test_case.gd"
## 重连与恢复编排测试（E3-T12 客户端侧）。

const ReconnectionService := preload("res://addons/godot_ai_agent/services/reconnection_service.gd")
const PluginContext := preload("res://addons/godot_ai_agent/core/plugin_context.gd")


class FakeSession extends RefCounted:
	signal connection_changed(state: String, detail: String)
	signal session_established(session: Dictionary)
	signal response_received(action: String, response: Dictionary)

	var resume_available := true
	var credentials := true
	var connect_calls := 0

	func request_connect() -> bool:
		connect_calls += 1
		return true

	func has_resume_token() -> bool:
		return resume_available

	func has_credentials() -> bool:
		return credentials

	func respond(action: String, response: Dictionary) -> void:
		response_received.emit(action, response)


class FakeSnapshot extends RefCounted:
	var latest_calls := 0
	var submit_calls := 0

	func request_latest() -> String:
		latest_calls += 1
		return "req_snapshot_latest"

	func submit() -> String:
		submit_calls += 1
		return "req_snapshot_submit"


class FakeEventSync extends RefCounted:
	var since_calls := 0

	func request_since(_after: int = -1) -> String:
		since_calls += 1
		return "req_events_since"


func _init() -> void:
	suite_name = "t12_reconnection"


func _make_service(timeout: float = 5.0):
	var ctx := PluginContext.new(null, "0.1.0", "4.5.1")
	ctx.set_config("reconnect_steps", [0.5])
	ctx.set_config("reconnect_jitter", 0.0)
	ctx.set_config("recovery_timeout_seconds", timeout)
	var service = ReconnectionService.new()
	assert_true(service.initialize(ctx))
	assert_true(service.start())
	return service


func _success() -> Dictionary:
	return {"success": true, "data": {}, "error": null}


func _failure(code: String) -> Dictionary:
	return {"success": false, "data": {}, "error": {"code": code, "message": code}}


## T12-UT-001：断线后暂停受保护操作，并按退避发起重连。
func test_loss_pauses_and_schedules_reconnect() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	service.attach_session(session)

	session.connection_changed.emit("CONNECTION_LOST", "")
	assert_eq(service.reconnect_state(), "WAITING")
	assert_true(service.is_protected_paused())
	assert_eq(session.connect_calls, 0)

	service.tick(0.6)
	assert_eq(session.connect_calls, 1)
	assert_eq(service.reconnect_state(), "RECONNECTING")
	assert_eq(int(service.status()["attempt"]), 1)
	service.stop("test")


## T12-UT-002：恢复必须同时拿到快照与事件补齐结果才进入 READY。
func test_recovery_requires_snapshot_and_events() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	var snapshot := FakeSnapshot.new()
	var events := FakeEventSync.new()
	service.attach_session(session)
	service.attach_snapshot(snapshot)
	service.attach_event_sync(events)

	session.connection_changed.emit("CONNECTION_LOST", "")
	service.tick(0.6)
	session.session_established.emit({})

	assert_eq(service.reconnect_state(), "RECOVERING")
	assert_eq(snapshot.latest_calls, 1)
	assert_eq(events.since_calls, 1)

	session.respond("editor.snapshot", _success())
	assert_eq(service.reconnect_state(), "RECOVERING")

	session.respond("bridge.events.since", _success())
	assert_eq(service.reconnect_state(), "READY")
	assert_false(service.is_protected_paused())
	assert_eq(str(service.status()["detail"]), "EVENT_CAUGHT_UP")
	service.stop("test")


## T12-UT-003：事件不可补齐时以全量快照为基准，并标记 SNAPSHOT_REQUIRED。
func test_sequence_gap_uses_snapshot() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	var snapshot := FakeSnapshot.new()
	var events := FakeEventSync.new()
	service.attach_session(session)
	service.attach_snapshot(snapshot)
	service.attach_event_sync(events)

	session.connection_changed.emit("CONNECTION_LOST", "")
	service.tick(0.6)
	session.session_established.emit({})
	session.respond("bridge.events.since", {
		"success": true,
		"data": {"snapshot_required": true},
		"error": null,
	})
	assert_eq(service.reconnect_state(), "RECOVERING")
	assert_eq(snapshot.latest_calls, 2)

	session.respond("editor.snapshot", _success())
	assert_eq(service.reconnect_state(), "READY")
	assert_eq(str(service.status()["detail"]), "SNAPSHOT_REQUIRED")
	service.stop("test")


## T12-UT-004：基准快照缺失时重新采集并提交，不直接失败。
func test_missing_snapshot_recaptures() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	var snapshot := FakeSnapshot.new()
	var events := FakeEventSync.new()
	service.attach_session(session)
	service.attach_snapshot(snapshot)
	service.attach_event_sync(events)

	session.connection_changed.emit("CONNECTION_LOST", "")
	service.tick(0.6)
	session.session_established.emit({})
	session.respond("editor.snapshot", _failure("SNAPSHOT_UNAVAILABLE"))
	session.respond("bridge.events.since", _success())

	assert_eq(snapshot.submit_calls, 1)
	assert_eq(service.reconnect_state(), "READY")
	assert_eq(str(service.status()["detail"]), "SNAPSHOT_RECAPTURED")
	service.stop("test")


## T12-UT-005：恢复超时或事件错误进入 UNKNOWN，受保护操作保持暂停。
func test_recovery_timeout_marks_unknown() -> void:
	var service = _make_service(0.05)
	var session := FakeSession.new()
	var snapshot := FakeSnapshot.new()
	var events := FakeEventSync.new()
	service.attach_session(session)
	service.attach_snapshot(snapshot)
	service.attach_event_sync(events)

	session.connection_changed.emit("CONNECTION_LOST", "")
	service.tick(0.6)
	session.session_established.emit({})
	service.tick(0.06)

	assert_eq(service.reconnect_state(), "UNKNOWN")
	assert_true(service.is_protected_paused())
	assert_eq(str(service.status()["error_code"]), "RECOVERY_TIMEOUT")
	service.stop("test")


## T12-UT-006：手动重连重置退避并立即发起连接。
func test_manual_reconnect_resets_backoff() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	service.attach_session(session)

	session.connection_changed.emit("CONNECTION_LOST", "")
	service.tick(0.6)
	assert_eq(session.connect_calls, 1)

	assert_true(service.request_reconnect())
	assert_eq(session.connect_calls, 2)
	assert_eq(int(service.status()["attempt"]), 1)
	assert_eq(service.reconnect_state(), "RECONNECTING")
	service.stop("test")
