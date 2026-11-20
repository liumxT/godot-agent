@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## 断线重连与恢复编排（E3-T12）。
##
## 状态：
##   IDLE → WAITING → RECONNECTING → RECOVERING → READY
##   任一阶段失败 → UNKNOWN（受保护操作保持暂停，等待用户或下次重连）
##
## 只做编排：退避由 ``Backoff`` 计算，恢复事实来自 ``editor.snapshot`` 与
## ``bridge.events.since`` 的响应；不盲目重放断线前未确认的未知请求。

signal reconnect_state_changed(state: String)
signal reconnect_scheduled(delay_seconds: float)
signal reconnect_attempted(attempt: int)
signal recovery_completed(state: String, detail: String)

const Backoff := preload("res://addons/godot_ai_agent/utilities/backoff.gd")
const ConnectionState := preload("res://addons/godot_ai_agent/bridge/connection_state.gd")

const SESSION_SERVICE_NAME := "editor_session_service"
const EVENT_SERVICE_NAME := "event_sync_service"
const SNAPSHOT_SERVICE_NAME := "snapshot_service"

const STATE_IDLE := "IDLE"
const STATE_WAITING := "WAITING"
const STATE_RECONNECTING := "RECONNECTING"
const STATE_RECOVERING := "RECOVERING"
const STATE_READY := "READY"
const STATE_UNKNOWN := "UNKNOWN"
const RECONNECT_STOPPED := "STOPPED"

const DEFAULT_STEPS: Array = [0.5, 1.0, 2.0, 4.0, 8.0, 15.0]
const DEFAULT_RECOVERY_TIMEOUT_SECONDS := 10.0

var _session: Object = null
var _event_sync: Object = null
var _snapshot: Object = null
var _backoff: Object = null

var _reconnect_state := STATE_IDLE
var _elapsed_ms := 0
var _next_attempt_ms := -1
var _attempt := 0
var _resuming := false
var _await_snapshot := false
var _await_since := false
var _snapshot_required := false
var _snapshot_from_capture := false
var _recovery_deadline_ms := -1
var _recovery_timeout_ms := int(DEFAULT_RECOVERY_TIMEOUT_SECONDS * 1000.0)
var _last_error := ""
var _last_detail := ""


func _initialize() -> bool:
	var steps: Array = context.get_config("reconnect_steps", DEFAULT_STEPS)
	_backoff = Backoff.new(steps, float(context.get_config("reconnect_jitter", 0.2)))
	_recovery_timeout_ms = int(
		float(context.get_config(
			"recovery_timeout_seconds", DEFAULT_RECOVERY_TIMEOUT_SECONDS
		)) * 1000.0
	)
	_attach_from_registry()
	return true


func _start() -> bool:
	if _session == null:
		_attach_from_registry()
	_bind_session()
	return true


func _tick(delta: float) -> void:
	_elapsed_ms += int(delta * 1000.0)
	var retrying := (
		_reconnect_state == STATE_WAITING or _reconnect_state == STATE_RECONNECTING
	)
	if retrying and _next_attempt_ms >= 0 and _elapsed_ms >= _next_attempt_ms:
		_attempt_reconnect()
		return
	if _reconnect_state == STATE_RECOVERING and _recovery_deadline_ms >= 0:
		if _elapsed_ms >= _recovery_deadline_ms:
			_finish_recovery(false, "RECOVERY_TIMEOUT")


func _stop(_reason: String) -> void:
	_unbind_session()
	_reconnect_state = RECONNECT_STOPPED
	_next_attempt_ms = -1
	_recovery_deadline_ms = -1


func _dispose() -> void:
	_session = null
	_event_sync = null
	_snapshot = null


## 注入依赖；测试可绕过注册表。
func attach_session(session: Object) -> void:
	if _session == session:
		return
	_unbind_session()
	_session = session
	if _state == STATE_RUNNING:
		_bind_session()


func attach_event_sync(service: Object) -> void:
	_event_sync = service


func attach_snapshot(service: Object) -> void:
	_snapshot = service


## 用户手动重连：重置退避并立即尝试。
func request_reconnect() -> bool:
	if _session == null or _reconnect_state == RECONNECT_STOPPED:
		return false
	_backoff.reset()
	_attempt = 0
	_next_attempt_ms = -1
	return _attempt_reconnect()


## 受保护操作是否必须暂停；只有 READY 视为可执行。
func is_protected_paused() -> bool:
	return _reconnect_state != STATE_READY


func reconnect_state() -> String:
	return _reconnect_state


func status() -> Dictionary:
	var base: Dictionary = super.status()
	base["reconnect_state"] = _reconnect_state
	base["attempt"] = _attempt
	base["next_retry_seconds"] = _seconds_until_retry()
	base["protected_paused"] = is_protected_paused()
	base["error_code"] = _last_error
	base["detail"] = _last_detail
	return base


func _seconds_until_retry() -> float:
	if _reconnect_state != STATE_WAITING and _reconnect_state != STATE_RECONNECTING:
		return 0.0
	if _next_attempt_ms < 0:
		return 0.0
	return maxf(0.0, float(_next_attempt_ms - _elapsed_ms) / 1000.0)


func _attach_from_registry() -> void:
	var registry: Variant = context.get_config("service_registry", null)
	if registry == null:
		return
	if _session == null:
		_session = registry.call("get_service", SESSION_SERVICE_NAME)
	if _event_sync == null:
		_event_sync = registry.call("get_service", EVENT_SERVICE_NAME)
	if _snapshot == null:
		_snapshot = registry.call("get_service", SNAPSHOT_SERVICE_NAME)


func _bind_session() -> void:
	if _session == null:
		return
	if not _session.is_connected("connection_changed", _on_connection_changed):
		_session.connect("connection_changed", _on_connection_changed)
	if not _session.is_connected("session_established", _on_session_established):
		_session.connect("session_established", _on_session_established)


func _unbind_session() -> void:
	_unbind_responses()
	if _session == null:
		return
	if _session.is_connected("connection_changed", _on_connection_changed):
		_session.disconnect("connection_changed", _on_connection_changed)
	if _session.is_connected("session_established", _on_session_established):
		_session.disconnect("session_established", _on_session_established)


func _on_connection_changed(state: String, _detail: String) -> void:
	match state:
		ConnectionState.CONNECTION_LOST:
			_on_lost()
		ConnectionState.DISCONNECTED:
			if _reconnect_state != RECONNECT_STOPPED:
				_set_reconnect_state(STATE_IDLE)
		_:
			pass


func _on_lost() -> void:
	_resuming = bool(_session.call("has_resume_token"))
	_await_snapshot = false
	_await_since = false
	_recovery_deadline_ms = -1
	_schedule_next()


func _schedule_next() -> void:
	if _reconnect_state == RECONNECT_STOPPED:
		return
	var delay := float(_backoff.next_delay())
	_next_attempt_ms = _elapsed_ms + int(delay * 1000.0)
	if _reconnect_state != STATE_RECONNECTING:
		_set_reconnect_state(STATE_WAITING)
	reconnect_scheduled.emit(delay)


func _attempt_reconnect() -> bool:
	if _session == null or _reconnect_state == RECONNECT_STOPPED:
		return false
	_resuming = bool(_session.call("has_resume_token"))
	var connected := bool(_session.call("request_connect"))
	_attempt += 1
	reconnect_attempted.emit(_attempt)
	if not connected:
		# 凭证缺失不会因重试而恢复，直接进入 UNKNOWN 并停止退避。
		if not bool(_session.call("has_credentials")):
			_last_error = "CREDENTIALS_MISSING"
			_set_reconnect_state(STATE_UNKNOWN)
			return false
		_schedule_next()
		return false
	_set_reconnect_state(STATE_RECONNECTING)
	# 连接可能在握手前失败，先安排下一次尝试；成功后由 _on_session_established 重置。
	_schedule_next()
	return true


func _on_session_established(_session_data: Dictionary) -> void:
	_backoff.reset()
	_attempt = 0
	_next_attempt_ms = -1
	_last_error = ""
	if _resuming:
		_begin_recovery()
	else:
		_set_reconnect_state(STATE_READY)


func _begin_recovery() -> void:
	_set_reconnect_state(STATE_RECOVERING)
	_snapshot_required = false
	_snapshot_from_capture = false
	_recovery_deadline_ms = _elapsed_ms + _recovery_timeout_ms
	_await_snapshot = false
	_await_since = false

	if _snapshot != null:
		_await_snapshot = not str(_snapshot.call("request_latest")).is_empty()
	if _event_sync != null:
		_await_since = not str(_event_sync.call("request_since")).is_empty()
	_bind_responses()
	if not _await_snapshot and not _await_since:
		# 没有任何可验证的恢复事实，不能宣称 READY。
		_finish_recovery(false, "RECOVERY_UNAVAILABLE")


func _bind_responses() -> void:
	if _session == null:
		return
	if not _session.is_connected("response_received", _on_response):
		_session.connect("response_received", _on_response)


func _unbind_responses() -> void:
	if _session == null:
		return
	if _session.is_connected("response_received", _on_response):
		_session.disconnect("response_received", _on_response)


func _on_response(action: String, response: Dictionary) -> void:
	if _reconnect_state != STATE_RECOVERING:
		return
	match action:
		"editor.snapshot":
			_handle_snapshot_response(response)
		"bridge.events.since":
			_handle_since_response(response)
		_:
			pass


func _handle_snapshot_response(response: Dictionary) -> void:
	if bool(response.get("success", false)):
		_await_snapshot = false
		_check_recovery()
		return
	var code := _response_error_code(response)
	if code == "SNAPSHOT_UNAVAILABLE":
		# 无基准快照：重新采集并提交，符合“强制全量快照”分支。
		_await_snapshot = false
		_snapshot_from_capture = true
		if _snapshot != null and str(_snapshot.call("submit")).is_empty():
			_finish_recovery(false, code)
			return
		_check_recovery()
		return
	_finish_recovery(false, code)


func _handle_since_response(response: Dictionary) -> void:
	if not bool(response.get("success", false)):
		_finish_recovery(false, _response_error_code(response))
		return
	var data: Dictionary = (
		response.get("data", {}) if typeof(response.get("data")) == TYPE_DICTIONARY else {}
	)
	if bool(data.get("snapshot_required", false)):
		# 事件已不可补齐：保留 UNKNOWN 语义，改用全量快照作为基准。
		_snapshot_required = true
		_await_snapshot = true
		if _snapshot != null and str(_snapshot.call("request_latest")).is_empty():
			_await_snapshot = false
	_await_since = false
	_check_recovery()


func _check_recovery() -> void:
	if _await_snapshot or _await_since:
		return
	var detail := "EVENT_CAUGHT_UP"
	if _snapshot_required:
		detail = "SNAPSHOT_REQUIRED"
	elif _snapshot_from_capture:
		detail = "SNAPSHOT_RECAPTURED"
	_finish_recovery(true, detail)


func _finish_recovery(ok: bool, detail: String) -> void:
	_await_snapshot = false
	_await_since = false
	_recovery_deadline_ms = -1
	_unbind_responses()
	_last_detail = detail
	if ok:
		_last_error = ""
		_set_reconnect_state(STATE_READY)
	else:
		_last_error = detail
		_set_reconnect_state(STATE_UNKNOWN)
	recovery_completed.emit(_reconnect_state, detail)


func _response_error_code(response: Dictionary) -> String:
	var error: Dictionary = (
		response.get("error", {}) if typeof(response.get("error")) == TYPE_DICTIONARY else {}
	)
	return str(error.get("code", "INFRASTRUCTURE_ERROR"))


func _set_reconnect_state(state: String) -> void:
	if _reconnect_state == state:
		return
	_reconnect_state = state
	reconnect_state_changed.emit(state)
