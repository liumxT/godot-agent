@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## Editor Session 客户端服务（E3-T06 / T07 / T08）。
##
## 负责：WS 连接 → HELLO → AUTH_RESPONSE → 保存 Session 与 Lease。
## Session/Lease 的权威在 Backend，本服务只缓存并暴露只读状态；
## 不自建心跳、不自行续租，也不允许 UI 直接触发网络调用。

signal connection_changed(state: String, detail: String)
signal session_established(session: Dictionary)
signal error_raised(code: String, message: String)
signal response_received(action: String, response: Dictionary)
signal request_failed(action: String, code: String, message: String)
signal event_received(event: Dictionary)
## Backend 下发的命令请求（E5-T28）；由 tool_command_service 消费。
signal command_requested(request: Dictionary)

const EditorBridgeClient := preload("res://addons/godot_ai_agent/bridge/editor_bridge_client.gd")
const ConnectionState := preload("res://addons/godot_ai_agent/bridge/connection_state.gd")
const EditorAuth := preload("res://addons/godot_ai_agent/services/editor_auth_service.gd")
const ProjectIdentity := preload("res://addons/godot_ai_agent/state/project_identity.gd")
const CredentialsStore := preload("res://addons/godot_ai_agent/utilities/credentials_store.gd")
const LeaseModel := preload("res://addons/godot_ai_agent/models/lease.gd")
const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")

const CONN_AUTHENTICATING := "AUTHENTICATING"
const CONN_AUTH_FAILED := "AUTH_FAILED"

const ERROR_CREDENTIALS_MISSING := "CREDENTIALS_MISSING"
const ERROR_CONTRACT_INVALID := "CONTRACT_INVALID"


var _client: Object = null
var _credentials: Object = null
var _connection := ConnectionState.DISCONNECTED
var _last_error_code := ""
var _last_error_message := ""
var _session: Dictionary = {}
var _lease: Dictionary = {}
## 断线后保留的恢复凭证；只由 Backend 判定是否有效（E3-T12）。
var _resume: Dictionary = {}
var _pending_challenge_id := ""
var _pending_challenge := ""
var _pending_requests: Dictionary = {}
var _request_counter := 0
var _editor_instance_id := ""
var _project_root := ""
var _project_name := ""
var _backend_url := ""


func _initialize() -> bool:
	_credentials = CredentialsStore.new()
	_credentials.load_credentials()
	var identity := ProjectIdentity.new()
	_project_root = str(context.get_config("project_root", ""))
	if _project_root.is_empty():
		_project_root = identity.root_path()
	_project_name = str(context.get_config("project_name", ""))
	if _project_name.is_empty():
		_project_name = identity.project_name()
	_editor_instance_id = str(context.get_config("editor_instance_id", ""))
	if _editor_instance_id.is_empty():
		_editor_instance_id = "edi_%012x" % (randi() % 0x1000000000000)
	_backend_url = _to_websocket_url(str(context.get_config(
		"backend_url", "http://127.0.0.1:8765"
	)))

	_client = EditorBridgeClient.new()
	_client.setup(
		_backend_url,
		float(context.get_config("handshake_timeout_seconds", 10.0)),
		int(context.get_config("queue_max", 64))
	)
	_client.state_changed.connect(_on_state_changed)
	_client.frame_received.connect(_on_frame_received)
	_client.connection_closed.connect(_on_connection_closed)
	_client.protocol_error.connect(_on_protocol_error)
	if not _credentials.has_credentials():
		_last_error_code = ERROR_CREDENTIALS_MISSING
		_last_error_message = "缺少客户端凭证，请先完成客户端登记"
	return true


func _start() -> bool:
	if bool(context.get_config("auto_connect", true)) and _credentials.has_credentials():
		request_connect()
	return true


func _tick(delta: float) -> void:
	if _client != null:
		_client.poll(delta)


func _stop(reason: String) -> void:
	if _client != null:
		_client.close(ConnectionState.CLOSE_NORMAL if reason.is_empty() else 1000, reason)
		_client = null
	_connection = ConnectionState.DISCONNECTED
	_pending_requests.clear()
	_lease.clear()
	_resume.clear()


func _dispose() -> void:
	_credentials = null
	_session.clear()
	_lease.clear()


## 由 UI 的「连接」按钮触发；不阻塞主线程。
func request_connect() -> bool:
	if _client == null:
		_set_error("SERVICE_UNAVAILABLE", "连接客户端不可用")
		return false
	if _client.is_open() or _connection == ConnectionState.CONNECTING:
		return false
	if not _credentials.has_credentials():
		_set_error(ERROR_CREDENTIALS_MISSING, "缺少客户端凭证，请先完成客户端登记")
		return false
	_last_error_code = ""
	_last_error_message = ""
	_set_connection(ConnectionState.CONNECTING, "正在连接后端")
	_client.connect_to_backend()
	return true


func request_disconnect() -> void:
	if _client == null:
		return
	if _client.is_open():
		_client.close(ConnectionState.CLOSE_NORMAL, "user_disconnect")
	_set_connection(ConnectionState.DISCONNECTED, "已断开")
	_lease.clear()
	_resume.clear()


func is_session_connected() -> bool:
	return _connection == ConnectionState.CONNECTED and not _session.is_empty()


## 是否持有可尝试恢复的 Session 凭证（不代表仍然有效）。
func has_resume_token() -> bool:
	return (
		not str(_resume.get("session_id", "")).is_empty()
		and not str(_resume.get("session_token", "")).is_empty()
	)


func resume_data() -> Dictionary:
	return _resume.duplicate(true)


func has_credentials() -> bool:
	return _credentials != null and bool(_credentials.has_credentials())


func connection_state() -> String:
	return _connection


func session_data() -> Dictionary:
	return _session.duplicate(true)


func lease_data() -> Dictionary:
	return _lease.duplicate(true)


func fencing_token() -> int:
	return int(_lease.get("fencing_token", 0))


## 发送业务请求；未连接或请求不合约时返回空字符串。
func send_request(action: String, payload: Dictionary, delivery: String = "PERSISTENT") -> String:
	if not is_session_connected() or _client == null:
		return ""
	_request_counter += 1
	var request_id := "req_%08x%06x" % [
		_request_counter,
		int(Time.get_ticks_usec()) & 0xFFFFFF,
	]
	var frame := {
		"protocol_version": "1.0",
		"request_id": request_id,
		"timestamp": _timestamp(),
		"session_id": str(_session.get("session_id", "")),
		"project_id": str(_session.get("project_id", "")),
		"action": action,
		"payload": payload.duplicate(true),
	}
	var errors: Array = Validator.validate_request(frame)
	if not errors.is_empty():
		_set_error(ERROR_CONTRACT_INVALID, str(errors[0]))
		return ""
	if not _client.send_frame(frame, delivery):
		return ""
	_pending_requests[request_id] = action
	return request_id


## 丢弃某 action 的超时请求，避免待响应表长期占用。
func drop_pending_requests(action: String) -> void:
	for request_id in _pending_requests.keys():
		if str(_pending_requests[request_id]) == action:
			_pending_requests.erase(request_id)


## 回复 Backend 下发的命令；连接不可用或响应不合契约时返回 false。
func send_response(
	request_id: String, success: bool, data: Dictionary = {}, error: Variant = null
) -> bool:
	if request_id.is_empty() or _client == null or not _client.is_open():
		return false
	var frame := {
		"protocol_version": "1.0",
		"request_id": request_id,
		"success": success,
		"data": null if not success and data.is_empty() else data,
		"error": error,
	}
	var errors: Array = Validator.validate_response(frame)
	if not errors.is_empty():
		_set_error(ERROR_CONTRACT_INVALID, str(errors[0]))
		return false
	return _client.send_frame(frame, "EPHEMERAL")


## 构造符合共享契约的 error 对象。
static func error_payload(
	code: String, message: String, details: Dictionary = {}, retryable: bool = false
) -> Dictionary:
	return {
		"code": code,
		"message": message if not message.is_empty() else "命令执行失败",
		"details": details,
		"retryable": retryable,
		"correlation_id": "unknown",
	}


## 受保护操作前的本地只读检查；最终判定仍在 Backend。
func can_use_lease() -> bool:
	return is_session_connected() and LeaseModel.is_usable(_lease)


func status() -> Dictionary:
	var base: Dictionary = super.status()
	base["connection"] = _connection
	base["backend_url"] = _backend_url
	base["session_id"] = str(_session.get("session_id", ""))
	base["project_id"] = str(_session.get("project_id", ""))
	base["editor_instance_id"] = _editor_instance_id
	base["lease"] = _lease.duplicate(true)
	base["lease_remaining_seconds"] = LeaseModel.remaining_seconds(_lease)
	base["resume_available"] = has_resume_token()
	base["error_code"] = _last_error_code
	base["message"] = _last_error_message
	return base


func _on_state_changed(_previous: String, current: String) -> void:
	if current == ConnectionState.CONNECTED:
		_send_hello()
	elif current == ConnectionState.CONNECTION_LOST:
		_set_connection(ConnectionState.CONNECTION_LOST, "连接中断")


func _send_hello() -> void:
	_pending_challenge_id = ""
	_pending_challenge = ""
	_set_connection(CONN_AUTHENTICATING, "正在进行身份认证")
	_client.send_frame(EditorAuth.make_hello(
		_credentials.client_id(),
		_editor_instance_id,
		_project_root,
		_project_name,
		str(context.godot_version()),
		str(context.plugin_version()),
		_resume
	))


func _on_frame_received(kind: String, frame: Dictionary) -> void:
	if kind == "request":
		_handle_command_request(frame)
		return
	if kind == "response":
		_handle_response(frame)
		return
	if kind == "event":
		var errors: Array = Validator.validate_event(frame)
		if errors.is_empty():
			event_received.emit(frame)
		else:
			_set_error(ERROR_CONTRACT_INVALID, str(errors[0]))
		return
	if kind != "control":
		return
	match str(frame.get("message_type", "")):
		"AUTH_CHALLENGE":
			_handle_auth_challenge(frame)
		"SESSION_CREATED":
			_handle_session_created(frame)
		"ERROR":
			_handle_error_control(frame)
		_:
			pass


func _handle_command_request(frame: Dictionary) -> void:
	var errors: Array = Validator.validate_request(frame)
	if not errors.is_empty():
		send_response(
			str(frame.get("request_id", "")),
			false,
			{},
			error_payload("INVALID_REQUEST", str(errors[0]))
		)
		return
	command_requested.emit(frame)


func _handle_response(frame: Dictionary) -> void:
	var errors: Array = Validator.validate_response(frame)
	if not errors.is_empty():
		_set_error(ERROR_CONTRACT_INVALID, str(errors[0]))
		return
	var request_id := str(frame.get("request_id", ""))
	var action := str(_pending_requests.get(request_id, ""))
	_pending_requests.erase(request_id)
	if action.is_empty():
		return
	if bool(frame.get("success", false)):
		var data: Dictionary = frame.get("data", {}) if typeof(frame.get("data")) == TYPE_DICTIONARY else {}
		if action == "session.heartbeat":
			var lease := LeaseModel.parse(data.get("lease", {}))
			if not lease.is_empty():
				_lease = lease
		response_received.emit(action, frame)
		return
	var error: Dictionary = frame.get("error", {}) if typeof(frame.get("error")) == TYPE_DICTIONARY else {}
	var code := str(error.get("code", "INFRASTRUCTURE_ERROR"))
	var message := str(error.get("message", ""))
	request_failed.emit(action, code, message)
	if code == "SESSION_SUSPENDED" or code.begins_with("LEASE_") or code == "FENCING_TOKEN_STALE":
		_lease.clear()
	response_received.emit(action, frame)


func _handle_auth_challenge(frame: Dictionary) -> void:
	var payload: Dictionary = frame.get("payload", {})
	_pending_challenge_id = str(payload.get("challenge_id", ""))
	_pending_challenge = str(payload.get("challenge", ""))
	if _pending_challenge_id.is_empty() or _pending_challenge.is_empty():
		_set_error(ERROR_CONTRACT_INVALID, "认证挑战缺少必需字段")
		return
	_client.send_frame(EditorAuth.make_auth_response(
		_pending_challenge_id,
		_pending_challenge,
		_credentials.client_secret()
	))


func _handle_session_created(frame: Dictionary) -> void:
	var payload: Dictionary = frame.get("payload", {})
	var errors: Array = Validator.validate_bridge_session_created(payload)
	if not errors.is_empty():
		_set_error(ERROR_CONTRACT_INVALID, str(errors[0]))
		return
	var lease := LeaseModel.parse(payload.get("lease", {}))
	if lease.is_empty():
		_set_error(ERROR_CONTRACT_INVALID, "Session 响应中的租约不合法")
		return
	_session = {
		"session_id": str(payload["session_id"]),
		"session_token": str(payload["session_token"]),
		"project_id": str(payload["project_id"]),
		"editor_instance_id": str(payload.get("editor_instance_id", _editor_instance_id)),
		"expires_at": str(payload["expires_at"]),
		"heartbeat_interval_seconds": int(payload.get("heartbeat_interval_seconds", 10)),
		"request_timeout_seconds": int(payload.get("request_timeout_seconds", 15)),
	}
	_lease = lease
	_resume = {
		"session_id": str(payload["session_id"]),
		"session_token": str(payload["session_token"]),
	}
	_last_error_code = ""
	_last_error_message = ""
	_set_connection(ConnectionState.CONNECTED, "已连接")
	session_established.emit(_session.duplicate(true))


func _handle_error_control(frame: Dictionary) -> void:
	var payload: Dictionary = frame.get("payload", {})
	var code := str(payload.get("code", "INFRASTRUCTURE_ERROR"))
	var message := str(payload.get("message", ""))
	if code.begins_with("AUTH_"):
		# 认证或恢复失败：保留的 Session 凭证已不可用，停止自动重试。
		_resume.clear()
		_connection = CONN_AUTH_FAILED
		_set_error(code, message)
	else:
		_set_error(code, message)


func _on_connection_closed(code: int, reason: String, reconnect: bool) -> void:
	if reconnect and not _session.is_empty():
		# 断线不等于 Session 失效：保留凭证供重连时向 Backend 申请恢复。
		_resume = {
			"session_id": str(_session.get("session_id", "")),
			"session_token": str(_session.get("session_token", "")),
		}
	elif not reconnect:
		_resume.clear()
	_pending_requests.clear()
	_lease.clear()
	_session.clear()
	if reconnect:
		_set_connection(ConnectionState.CONNECTION_LOST, "连接中断（%d）" % code)
	else:
		_set_connection(ConnectionState.DISCONNECTED, reason if not reason.is_empty() else "已断开")
	if code >= 4400:
		_last_error_code = str(code)
		_last_error_message = reason


func _on_protocol_error(code: String, message: String) -> void:
	_set_error(code, message)


func _set_connection(state: String, detail: String) -> void:
	if _connection == state:
		connection_changed.emit(state, detail)
		return
	_connection = state
	connection_changed.emit(state, detail)


func _set_error(code: String, message: String) -> void:
	_last_error_code = code
	_last_error_message = message
	if code.begins_with("AUTH_"):
		_connection = CONN_AUTH_FAILED
	error_raised.emit(code, message)


func _timestamp() -> String:
	return Time.get_datetime_string_from_unix_time(
		int(Time.get_unix_time_from_system())
	) + "Z"


func _to_websocket_url(url: String) -> String:
	var text := url.strip_edges()
	if text.begins_with("ws://") or text.begins_with("wss://"):
		return text
	if text.begins_with("https://"):
		text = "wss://" + text.substr(8)
	elif text.begins_with("http://"):
		text = "ws://" + text.substr(7)
	if text.ends_with("/"):
		text = text.substr(0, text.length() - 1)
	return text + "/api/v1/ws/editor"
