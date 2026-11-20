@tool
extends "res://tests/test_case.gd"
## 事件同步服务测试（E3-T10 客户端侧）。

const EventSyncService := preload("res://addons/godot_ai_agent/services/event_sync_service.gd")
const PluginContext := preload("res://addons/godot_ai_agent/core/plugin_context.gd")

const SESSION_ID := "ses_000000000001"
const PROJECT_ID := "prj_abcdefghijkl"


class FakeSession extends RefCounted:
	signal connection_changed(state: String, detail: String)
	signal response_received(action: String, response: Dictionary)
	signal event_received(event: Dictionary)

	var connected := true
	var requests: Array = []
	var counter := 0

	func is_session_connected() -> bool:
		return connected

	func session_data() -> Dictionary:
		return {
			"session_id": SESSION_ID,
			"project_id": PROJECT_ID,
			"editor_instance_id": "edi_0123456789ab",
		}

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

	func respond(action: String, response: Dictionary) -> void:
		response_received.emit(action, response)


func _init() -> void:
	suite_name = "t10_event_sync"


func _make_service():
	var ctx = PluginContext.new(null, "0.1.0", "4.5.1")
	ctx.set_config("event_retry_seconds", 5.0)
	var service = EventSyncService.new()
	assert_true(service.initialize(ctx))
	assert_true(service.start())
	return service


func _requests_of(session, action: String) -> Array:
	var result: Array = []
	for request in session.requests:
		if str(request["action"]) == action:
			result.append(request)
	return result


func _response(data: Dictionary) -> Dictionary:
	return {
		"protocol_version": "1.0",
		"request_id": "req_fake0001",
		"success": true,
		"data": data,
		"error": null,
	}


func _backend_event(event_id: String, sequence: int) -> Dictionary:
	return {
		"protocol_version": "1.0",
		"event_id": event_id,
		"event_type": "project.changed",
		"timestamp": Time.get_datetime_string_from_unix_time(
			int(Time.get_unix_time_from_system())
		) + "Z",
		"source": "backend",
		"payload": {"sequence": sequence, "event_version": 1},
	}


## T10-UT-001：PERSISTENT 事件入待确认队列，确认后移除。
func test_publish_tracks_until_accepted() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	service.attach_session(session)

	var request_id := service.publish_event("scene.changed", {"scene": "res://main.tscn"})
	assert_true(request_id.length() > 0)
	var publishes := _requests_of(session, "bridge.events.publish")
	assert_eq(publishes.size(), 1)
	var event: Dictionary = publishes[0]["payload"]["events"][0]
	assert_eq(str(event["source"]), "plugin")
	assert_eq(str(event["session_id"]), SESSION_ID)
	assert_true(str(event["event_id"]).begins_with("evt_"))
	assert_eq(service.pending_count(), 1)

	session.respond("bridge.events.publish", _response({
		"accepted": [event["event_id"]],
		"latest_sequence": 1,
		"persisted": 1,
	}))
	assert_eq(service.pending_count(), 0)
	assert_eq(service.last_sequence(), 1)
	service.stop("test")


## T10-UT-002：同一 event_id 在去重窗口内只发送一次。
func test_duplicate_event_id_is_skipped() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	service.attach_session(session)

	var first := service.publish_event("scene.changed", {}, "PERSISTENT", "evt_fixed000001")
	var second := service.publish_event("scene.changed", {}, "PERSISTENT", "evt_fixed000001")

	assert_true(first.length() > 0)
	assert_eq(second, "")
	assert_eq(_requests_of(session, "bridge.events.publish").size(), 1)
	assert_eq(service.seen_count(), 1)
	service.stop("test")


## T10-UT-003：since 补齐事件、支持 snapshot_required 与批量 ack。
func test_since_ingests_and_acks() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	var received: Array = []
	var snapshots: Array = []
	service.events_received.connect(func(events): received.append(events.size()))
	service.snapshot_required.connect(func(): snapshots.append(true))
	service.attach_session(session)

	session.respond("bridge.events.since", _response({
		"events": [
			_backend_event("evt_backend0001", 1),
			_backend_event("evt_backend0002", 2),
		],
		"latest_sequence": 2,
		"snapshot_required": true,
	}))
	assert_eq(received, [2])
	assert_eq(snapshots.size(), 1)

	var ack_id := service.flush_ack()
	assert_eq(ack_id, "")
	var acks := _requests_of(session, "bridge.events.ack")
	assert_eq(acks.size(), 1)
	assert_eq(acks[0]["payload"]["event_ids"].size(), 2)
	assert_eq(int(acks[0]["payload"]["last_sequence"]), 2)

	session.respond("bridge.events.since", _response({
		"events": [
			_backend_event("evt_backend0001", 1),
			_backend_event("evt_backend0002", 2),
		],
		"latest_sequence": 2,
		"snapshot_required": false,
	}))
	assert_eq(received, [2])
	service.stop("test")


## T10-UT-004：去重窗口固定为 256 个 event_id。
func test_seen_window_is_bounded() -> void:
	var service = _make_service()
	var session := FakeSession.new()
	service.attach_session(session)

	var events: Array = []
	for index in 260:
		events.append(_backend_event("evt_window%04d" % index, index + 1))
	session.respond("bridge.events.since", _response({
		"events": events,
		"latest_sequence": 260,
		"snapshot_required": false,
	}))

	assert_eq(service.seen_count(), 256)
	service.stop("test")
