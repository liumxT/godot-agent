@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## 心跳服务（E3-T09）。
##
## 周期发送 ``session.heartbeat``，续期由 Backend 完成；本地只统计响应缺失。
## 连续 ``heartbeat_max_missed`` 次未响应时进入 LOST 并广播 ``connection_lost``，
## 供上层暂停受保护操作。

signal connection_lost(detail: String)
signal resync_required()
signal heartbeat_done(sequence: int)

const ConnectionState := preload("res://addons/godot_ai_agent/bridge/connection_state.gd")

const SERVICE_NAME := "heartbeat_service"
const SESSION_SERVICE_NAME := "editor_session_service"

const STATE_IDLE := "IDLE"
const STATE_HEALTHY := "HEALTHY"
const STATE_DEGRADED := "DEGRADED"
const STATE_LOST := "LOST"

const DEFAULT_INTERVAL_SECONDS := 10.0
const DEFAULT_TIMEOUT_SECONDS := 30.0
const DEFAULT_MAX_MISSED := 3


var _session: Object = null
var _interval_ms := int(DEFAULT_INTERVAL_SECONDS * 1000)
var _timeout_ms := int(DEFAULT_TIMEOUT_SECONDS * 1000)
var _max_missed := DEFAULT_MAX_MISSED
var _run_status := "STOPPED"

var _elapsed_ms := 0
var _next_due_ms := 0
var _pending_since_ms := -1
var _sequence := 0
var _missed := 0
var _health := STATE_IDLE
var _last_server_time := ""
var _last_error := ""


func _initialize() -> bool:
	_interval_ms = int(float(context.get_config(
		"heartbeat_interval_seconds", DEFAULT_INTERVAL_SECONDS
	)) * 1000.0)
	_timeout_ms = int(float(context.get_config(
		"heartbeat_timeout_seconds", DEFAULT_TIMEOUT_SECONDS
	)) * 1000.0)
	_max_missed = maxi(1, int(context.get_config("heartbeat_max_missed", DEFAULT_MAX_MISSED)))
	_run_status = str(context.get_config("run_status", "STOPPED"))
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
	if _pending_since_ms >= 0 and _elapsed_ms - _pending_since_ms > _timeout_ms:
		_register_miss("心跳响应超时")
	if _health != STATE_LOST and _elapsed_ms >= _next_due_ms:
		_send_heartbeat()


func _stop(_reason: String) -> void:
	_unbind_session()
	_health = STATE_IDLE
	_pending_since_ms = -1


func _dispose() -> void:
	_session = null


## 注入 Session 服务；注册表可用时由 _initialize 自动完成。
func attach_session(session: Object) -> void:
	if _session == session:
		return
	_unbind_session()
	_session = session
	if _session != null and _state == STATE_RUNNING:
		_bind_session()


func is_healthy() -> bool:
	return _health == STATE_HEALTHY or _health == STATE_DEGRADED


func sequence() -> int:
	return _sequence


func status() -> Dictionary:
	var base: Dictionary = super.status()
	base["health"] = _health
	base["sequence"] = _sequence
	base["missed"] = _missed
	base["last_server_time"] = _last_server_time
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
	if bool(_session.call("is_session_connected")):
		_health = STATE_HEALTHY
		_send_heartbeat()


func _unbind_session() -> void:
	if _session == null:
		return
	if _session.is_connected("connection_changed", _on_connection_changed):
		_session.disconnect("connection_changed", _on_connection_changed)
	if _session.is_connected("response_received", _on_response):
		_session.disconnect("response_received", _on_response)


func _on_connection_changed(state: String, _detail: String) -> void:
	if state == ConnectionState.CONNECTED:
		_missed = 0
		_last_error = ""
		_pending_since_ms = -1
		_health = STATE_HEALTHY
		_send_heartbeat()
		return
	if (
		state == ConnectionState.CONNECTION_LOST
		or state == ConnectionState.DISCONNECTED
		or state == "AUTH_FAILED"
	):
		_health = STATE_IDLE
		_pending_since_ms = -1
		_next_due_ms = 0


func _send_heartbeat() -> void:
	if _session == null or not bool(_session.call("is_session_connected")):
		return
	_sequence += 1
	var payload := {
		"sequence": _sequence,
		"client_time": _timestamp(),
		"state_digest": _state_digest(),
		"run_status": _run_status,
	}
	var request_id := str(_session.call(
		"send_request", "session.heartbeat", payload, "EPHEMERAL"
	))
	if request_id.is_empty():
		_register_miss("心跳发送失败")
		return
	_pending_since_ms = _elapsed_ms
	_next_due_ms = _elapsed_ms + _interval_ms


func _on_response(action: String, response: Dictionary) -> void:
	if action != "session.heartbeat":
		return
	if bool(response.get("success", false)):
		var data: Dictionary = (
			response.get("data", {}) if typeof(response.get("data")) == TYPE_DICTIONARY else {}
		)
		_missed = 0
		_last_error = ""
		_health = STATE_HEALTHY
		_pending_since_ms = -1
		_last_server_time = str(data.get("server_time", ""))
		_next_due_ms = _elapsed_ms + _interval_ms
		heartbeat_done.emit(_sequence)
		if bool(data.get("resync_required", false)):
			resync_required.emit()
		return
	var error: Dictionary = (
		response.get("error", {}) if typeof(response.get("error")) == TYPE_DICTIONARY else {}
	)
	_register_miss(str(error.get("code", "HEARTBEAT_FAILED")))


func _register_miss(detail: String) -> void:
	_missed += 1
	_pending_since_ms = -1
	_last_error = detail
	if _session != null and _session.has_method("drop_pending_requests"):
		_session.call("drop_pending_requests", "session.heartbeat")
	_next_due_ms = _elapsed_ms
	if _missed < _max_missed:
		_health = STATE_DEGRADED
		return
	_health = STATE_LOST
	_next_due_ms = _elapsed_ms + _interval_ms
	connection_lost.emit(detail)


func _state_digest() -> String:
	var raw := "%s:%d" % [str(_session.call("session_data").get("session_id", "")), _sequence]
	return raw.sha256_text()


func _timestamp() -> String:
	return Time.get_datetime_string_from_unix_time(
		int(Time.get_unix_time_from_system())
	) + "Z"
