@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## 事件同步服务（E3-T10）。
##
## 上行：PERSISTENT 事件进入待确认队列，响应或重试成功后才移除；
## 下行：通过 ``bridge.events.since`` 按 sequence 补齐，批量子确认。
## 去重窗口固定 256 个 event_id，避免重连后重复消费。

signal events_received(events: Array)
signal snapshot_required()
signal publish_failed(code: String, message: String)

const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")
const ConnectionState := preload("res://addons/godot_ai_agent/bridge/connection_state.gd")

const SERVICE_NAME := "event_sync_service"
const SESSION_SERVICE_NAME := "editor_session_service"

const SEEN_LIMIT := 256
const ACK_BATCH := 16
const MAX_PUBLISH_BATCH := 100
const SINCE_LIMIT := 500
const DEFAULT_RETRY_MS := 5000

const PERSISTENCE_PERSISTENT := "PERSISTENT"
const PERSISTENCE_EPHEMERAL := "EPHEMERAL"

var _session: Object = null
var _elapsed_ms := 0
var _next_retry_ms := 3000
var _retry_ms := DEFAULT_RETRY_MS

var _sequence := 0
var _last_uplink_sequence := 0
var _last_received_sequence := 0

var _seen: Array = []
var _seen_lookup: Dictionary = {}
var _unacked: Dictionary = {}
var _pending_ack: Array = []
var _last_error := ""


func _initialize() -> bool:
	_retry_ms = int(float(context.get_config("event_retry_seconds", 5.0)) * 1000.0)
	_attach_from_registry()
	return true


func _start() -> bool:
	if _session == null:
		_attach_from_registry()
	if _session != null:
		_bind_session()
	return true


func _tick(delta: float) -> void:
	_elapsed_ms += int(delta * 1000.0)
	if _session == null or not bool(_session.call("is_session_connected")):
		return
	if _unacked.is_empty() or _elapsed_ms < _next_retry_ms:
		return
	_resend_unacked()


func _stop(_reason: String) -> void:
	_unbind_session()
	_unacked.clear()
	_pending_ack.clear()


func _dispose() -> void:
	_session = null
	_seen.clear()
	_seen_lookup.clear()


## 注入 Session 服务；注册表可用时由 _initialize 自动完成。
func attach_session(session: Object) -> void:
	if _session == session:
		return
	_unbind_session()
	_session = session
	if _session != null and _state == STATE_RUNNING:
		_bind_session()


func publish_event(
	event_type: String,
	payload: Dictionary,
	persistence: String = PERSISTENCE_PERSISTENT,
	event_id: String = ""
) -> String:
	"""发布单条上行事件，返回 request_id；被去重或未连接时返回空串。"""

	if _session == null or not bool(_session.call("is_session_connected")):
		return ""
	var resolved_id := event_id
	if resolved_id.is_empty():
		resolved_id = _next_event_id()
	var event_payload := payload.duplicate(true)
	if persistence == PERSISTENCE_EPHEMERAL:
		event_payload["persistence"] = PERSISTENCE_EPHEMERAL
	var event := {
		"protocol_version": "1.0",
		"event_id": resolved_id,
		"event_type": event_type,
		"timestamp": _timestamp(),
		"source": "plugin",
		"session_id": str(_session.call("session_data").get("session_id", "")),
		"project_id": str(_session.call("session_data").get("project_id", "")),
		"payload": event_payload,
	}
	var errors: Array = Validator.validate_event(event)
	if not errors.is_empty():
		_last_error = str(errors[0])
		publish_failed.emit("CONTRACT_INVALID", _last_error)
		return ""
	if not _remember(resolved_id):
		return ""
	if persistence == PERSISTENCE_PERSISTENT:
		_unacked[resolved_id] = event
	return _send_publish([event], persistence)


## 按服务端 sequence 补齐下行事件。
func request_since(after_sequence: int = -1) -> String:
	if _session == null or not bool(_session.call("is_session_connected")):
		return ""
	var after := _last_received_sequence if after_sequence < 0 else after_sequence
	return str(_session.call(
		"send_request",
		"bridge.events.since",
		{"after_sequence": after, "limit": SINCE_LIMIT},
		"PERSISTENT"
	))


## 立即发送已收到的下行事件确认。
func flush_ack() -> String:
	if _session == null or _pending_ack.is_empty():
		return ""
	var ids := _pending_ack.duplicate()
	_pending_ack.clear()
	var request_id := str(_session.call(
		"send_request",
		"bridge.events.ack",
		{"event_ids": ids, "last_sequence": _last_received_sequence},
		"PERSISTENT"
	))
	if request_id.is_empty():
		_pending_ack = ids + _pending_ack
	return request_id


func heat_retry() -> String:
	"""强制重发未确认事件；供重连后立即恢复。"""

	if _unacked.is_empty():
		return ""
	return _resend_unacked()


func pending_count() -> int:
	return _unacked.size()


func seen_count() -> int:
	return _seen.size()


func last_sequence() -> int:
	return _last_uplink_sequence


func status() -> Dictionary:
	var base: Dictionary = super.status()
	base["pending"] = _unacked.size()
	base["last_sequence"] = _last_uplink_sequence
	base["last_received_sequence"] = _last_received_sequence
	base["error_code"] = _last_error
	return base


func _attach_from_registry() -> void:
	if _session != null:
		return
	var registry: Variant = context.get_config("service_registry", null)
	if registry == null:
		return
	_session = registry.call("get_service", SESSION_SERVICE_NAME)


func _bind_session() -> void:
	if _session == null:
		return
	if not _session.is_connected("connection_changed", _on_connection_changed):
		_session.connect("connection_changed", _on_connection_changed)
	if not _session.is_connected("response_received", _on_response):
		_session.connect("response_received", _on_response)
	if not _session.is_connected("event_received", _on_event):
		_session.connect("event_received", _on_event)
	if bool(_session.call("is_session_connected")):
		_resume()


func _unbind_session() -> void:
	if _session == null:
		return
	if _session.is_connected("connection_changed", _on_connection_changed):
		_session.disconnect("connection_changed", _on_connection_changed)
	if _session.is_connected("response_received", _on_response):
		_session.disconnect("response_received", _on_response)
	if _session.is_connected("event_received", _on_event):
		_session.disconnect("event_received", _on_event)


func _on_connection_changed(state: String, _detail: String) -> void:
	if state != ConnectionState.CONNECTED:
		return
	_resume()


func _resume() -> void:
	request_since()
	heat_retry()


func _on_event(event: Dictionary) -> void:
	_ingest([event])


func _on_response(action: String, response: Dictionary) -> void:
	match action:
		"bridge.events.publish":
			if bool(response.get("success", false)):
				_handle_publish_success(response)
			else:
				var error: Dictionary = (
					response.get("error", {})
					if typeof(response.get("error")) == TYPE_DICTIONARY
					else {}
				)
				_last_error = str(error.get("code", "PUBLISH_FAILED"))
				_next_retry_ms = _elapsed_ms + _retry_ms
				publish_failed.emit(_last_error, str(error.get("message", "")))
		"bridge.events.since":
			if bool(response.get("success", false)):
				_handle_since_success(response)
			else:
				_next_retry_ms = _elapsed_ms + _retry_ms
		"bridge.events.ack":
			pass


func _handle_publish_success(response: Dictionary) -> void:
	var data: Dictionary = (
		response.get("data", {}) if typeof(response.get("data")) == TYPE_DICTIONARY else {}
	)
	var accepted: Array = data.get("accepted", [])
	for event_id in accepted:
		_unacked.erase(str(event_id))
	_last_uplink_sequence = maxi(_last_uplink_sequence, int(data.get("latest_sequence", 0)))
	_next_retry_ms = _elapsed_ms + _retry_ms


func _handle_since_success(response: Dictionary) -> void:
	var data: Dictionary = (
		response.get("data", {}) if typeof(response.get("data")) == TYPE_DICTIONARY else {}
	)
	var incoming: Array = data.get("events", [])
	_ingest(incoming)
	if bool(data.get("snapshot_required", false)):
		snapshot_required.emit()
	if not _pending_ack.is_empty():
		flush_ack()


func _ingest(events: Array) -> void:
	var accepted: Array = []
	for raw in events:
		if typeof(raw) != TYPE_DICTIONARY:
			continue
		var event: Dictionary = raw
		var errors: Array = Validator.validate_event(event)
		if not errors.is_empty():
			_last_error = str(errors[0])
			continue
		var event_id := str(event.get("event_id", ""))
		if not _remember(event_id):
			continue
		var payload: Dictionary = (
			event.get("payload", {}) if typeof(event.get("payload")) == TYPE_DICTIONARY else {}
		)
		_last_received_sequence = maxi(
			_last_received_sequence, int(payload.get("sequence", 0))
		)
		_pending_ack.append(event_id)
		accepted.append(event)
	if not accepted.is_empty():
		events_received.emit(accepted)
	if _pending_ack.size() >= ACK_BATCH:
		flush_ack()


func _send_publish(events: Array, persistence: String) -> String:
	if _session == null or events.is_empty():
		return ""
	var delivery := PERSISTENCE_EPHEMERAL if persistence == PERSISTENCE_EPHEMERAL else "PERSISTENT"
	var request_id := str(_session.call(
		"send_request", "bridge.events.publish", {"events": events}, delivery
	))
	if request_id.is_empty():
		_next_retry_ms = _elapsed_ms + _retry_ms
		return ""
	_next_retry_ms = _elapsed_ms + _retry_ms
	return request_id


func _resend_unacked() -> String:
	var events: Array = []
	for event_id in _unacked:
		events.append(_unacked[event_id])
		if events.size() >= MAX_PUBLISH_BATCH:
			break
	if events.is_empty():
		return ""
	return _send_publish(events, PERSISTENCE_PERSISTENT)


func _remember(event_id: String) -> bool:
	if event_id.is_empty() or _seen_lookup.has(event_id):
		return false
	_seen.append(event_id)
	_seen_lookup[event_id] = true
	if _seen.size() > SEEN_LIMIT:
		var oldest := str(_seen.pop_front())
		_seen_lookup.erase(oldest)
	return true


func _next_event_id() -> String:
	_sequence += 1
	return "evt_%012x" % (
		(int(Time.get_ticks_usec()) ^ (_sequence * 0x9E3779B1)) & 0xFFFFFFFFFFFF
	)


func _timestamp() -> String:
	return Time.get_datetime_string_from_unix_time(
		int(Time.get_unix_time_from_system())
	) + "Z"
