extends Node
## Runtime Bridge（E3-T16）。
##
## 游戏进程侧独立通道：由插件菜单显式注入 autoload 后才启用。
## 使用独立的 Runtime 凭证与独立端点，不继承 Editor 的 Session、Lease 或写权限，
## 只上报自身运行状态。插件不会静默修改 ``project.godot``。

const EditorBridgeClient := preload("res://addons/godot_ai_agent/bridge/editor_bridge_client.gd")
const EditorAuth := preload("res://addons/godot_ai_agent/services/editor_auth_service.gd")
const CredentialsStore := preload("res://addons/godot_ai_agent/utilities/credentials_store.gd")
const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")

const AUTOLOAD_NAME := "GodotAIRuntimeBridge"
const SCRIPT_PATH := "res://addons/godot_ai_agent/runtime/runtime_bridge.gd"

const ENV_BACKEND_URL := "GODOT_AI_BACKEND_URL"
const ENV_CREDENTIALS := "GODOT_AI_RUNTIME_CREDENTIALS"
const DEFAULT_CREDENTIALS_PATH := "user://godot_ai_agent/runtime_credentials.json"
const DEFAULT_BACKEND_URL := "http://127.0.0.1:8765"
const RUNTIME_ENDPOINT := "/api/v1/ws/runtime"

const REPORT_ACTION := "bridge.runtime.report"
const REPORT_INTERVAL_SECONDS := 5.0
const HANDSHAKE_TIMEOUT_SECONDS := 10.0
const RECONNECT_INTERVAL_SECONDS := 5.0

const PHASE_DISABLED := "DISABLED"
const PHASE_CONNECTING := "CONNECTING"
const PHASE_AUTHENTICATING := "AUTHENTICATING"
const PHASE_REGISTERED := "REGISTERED"
const PHASE_ERROR := "ERROR"

const STATUS_RUNNING := "RUNNING"
const STATUS_STOPPED := "STOPPED"

signal runtime_registered(runtime_instance_id: String)
signal runtime_failed(code: String, message: String)

static var _active_instance_id := ""

var _client: Object = null
var _credentials: Object = null
var _phase := PHASE_DISABLED
var _backend_url := ""
var _runtime_instance_id := ""
var _started_at := ""
var _project_fingerprint := ""
var _report_interval := REPORT_INTERVAL_SECONDS
var _elapsed := 0.0
var _reconnect_elapsed := 0.0
var _last_error := ""
var _request_counter := 0


func _ready() -> void:
	set_process(true)
	_started_at = utc_timestamp()
	_runtime_instance_id = new_runtime_instance_id()
	_active_instance_id = _runtime_instance_id
	_project_fingerprint = project_fingerprint(ProjectSettings.globalize_path("res://"))
	var path := str(OS.get_environment(ENV_CREDENTIALS))
	if path.is_empty():
		path = DEFAULT_CREDENTIALS_PATH
	_credentials = CredentialsStore.new(path)
	if not _credentials.load_credentials():
		_phase = PHASE_DISABLED
		_last_error = "CREDENTIALS_MISSING"
		return
	_backend_url = to_runtime_url(_configured_backend_url())
	_client = EditorBridgeClient.new()
	_client.setup(_backend_url, HANDSHAKE_TIMEOUT_SECONDS, 64)
	_client.state_changed.connect(_on_state_changed)
	_client.frame_received.connect(_on_frame_received)
	_client.connection_closed.connect(_on_connection_closed)
	_client.protocol_error.connect(_on_protocol_error)
	_phase = PHASE_CONNECTING
	_client.connect_to_backend()


func _process(delta: float) -> void:
	if _client == null:
		return
	_client.poll(delta)
	_tick_reconnect(delta)
	_tick_report(delta)


## 游戏退出属于正常停止：先上报 STOPPED，再关闭连接。
func _exit_tree() -> void:
	if _client == null:
		return
	if _phase == PHASE_REGISTERED:
		_report(STATUS_STOPPED)
		_client.poll(0.0)
	_client.close(1000, "runtime stopped")
	_client = null
	_phase = PHASE_DISABLED


func status() -> Dictionary:
	return {
		"phase": _phase,
		"runtime_instance_id": _runtime_instance_id,
		"fingerprint": _project_fingerprint,
		"error_code": _last_error,
		"registered": _phase == PHASE_REGISTERED,
	}


# --- 纯函数：便于在无网络环境下验证身份与帧结构 ---


## 与 Backend ``Path.resolve()`` 的字符串形式保持一致：去尾分隔符，
## Windows 使用反斜杠，其他平台使用正斜杠。
static func normalize_path(raw: String) -> String:
	var text := raw.strip_edges()
	if text.is_empty():
		return ""
	var forward := text.replace("\\", "/")
	while forward.length() > 1 and forward.ends_with("/"):
		forward = forward.substr(0, forward.length() - 1)
	if OS.get_name() == "Windows":
		return forward.replace("/", "\\")
	return forward


## ``sha256(realpath(project_root))`` 的十六进制摘要，用于匹配已登记项目。
static func project_fingerprint(raw: String) -> String:
	var context := HashingContext.new()
	if context.start(HashingContext.HASH_SHA256) != OK:
		return ""
	context.update(normalize_path(raw).to_utf8_buffer())
	return context.finish().hex_encode()


static func new_runtime_instance_id() -> String:
	if not _active_instance_id.is_empty():
		return _active_instance_id
	return "rti_%012x" % (((randi() << 17) ^ randi()) & 0xFFFFFFFFFFFF)


static func build_mode() -> String:
	return "debug" if OS.has_feature("debug") else "release"


## Runtime HELLO：``project_root`` 使用 ``res://``，真实路径只以指纹形式出现。
static func build_hello_payload(
	client_id: String,
	runtime_instance_id: String,
	fingerprint: String,
	process_id: int,
	started_at: String,
	godot_version: String,
	mode: String = "debug",
	status: String = STATUS_RUNNING
) -> Dictionary:
	return {
		"client_id": client_id,
		"runtime_instance_id": runtime_instance_id,
		"project_root": "res://",
		"project_fingerprint": fingerprint,
		"process_id": process_id,
		"started_at": started_at,
		"godot_version": godot_version,
		"build_mode": mode,
		"status": status,
	}


static func make_hello(
	client_id: String,
	runtime_instance_id: String,
	fingerprint: String,
	process_id: int,
	started_at: String,
	godot_version: String,
	mode: String = "debug"
) -> Dictionary:
	return EditorAuth.make_control("HELLO", build_hello_payload(
		client_id,
		runtime_instance_id,
		fingerprint,
		process_id,
		started_at,
		godot_version,
		mode
	))


static func build_report_payload(
	runtime_instance_id: String,
	status: String,
	timestamp: String = ""
) -> Dictionary:
	return {
		"runtime_instance_id": runtime_instance_id,
		"status": status,
		"timestamp": timestamp if not timestamp.is_empty() else utc_timestamp(),
	}


static func make_report_frame(runtime_instance_id: String, status: String) -> Dictionary:
	return {
		"protocol_version": "1.0",
		"request_id": "req_rt%08x" % (randi() % 0x100000000),
		"timestamp": utc_timestamp(),
		"action": REPORT_ACTION,
		"payload": build_report_payload(runtime_instance_id, status),
	}


static func utc_timestamp() -> String:
	return Time.get_datetime_string_from_system(true) + "Z"


## 把 Backend HTTP(S) 地址转换为 Runtime WebSocket 地址。
static func to_runtime_url(url: String) -> String:
	var text := url.strip_edges()
	if text.begins_with("ws://") or text.begins_with("wss://"):
		if text.ends_with(RUNTIME_ENDPOINT):
			return text
		if text.ends_with("/"):
			text = text.substr(0, text.length() - 1)
		return text + RUNTIME_ENDPOINT
	if text.begins_with("https://"):
		text = "wss://" + text.substr(8)
	elif text.begins_with("http://"):
		text = "ws://" + text.substr(7)
	if text.ends_with("/"):
		text = text.substr(0, text.length() - 1)
	return text + RUNTIME_ENDPOINT


# --- 连接与上报 ---


func _configured_backend_url() -> String:
	var from_env := str(OS.get_environment(ENV_BACKEND_URL))
	if not from_env.is_empty():
		return from_env
	return str(ProjectSettings.get_setting("godot_ai_agent/backend_url", DEFAULT_BACKEND_URL))


func _on_state_changed(_previous: String, current: String) -> void:
	if current == "CONNECTED":
		_send_hello()


func _send_hello() -> void:
	_phase = PHASE_AUTHENTICATING
	_client.send_frame(make_hello(
		_credentials.client_id(),
		_runtime_instance_id,
		_project_fingerprint,
		OS.get_process_id(),
		_started_at,
		str(Engine.get_version_info().get("string", "unknown")),
		build_mode()
	))


func _on_frame_received(kind: String, frame: Dictionary) -> void:
	if kind == "control":
		match str(frame.get("message_type", "")):
			"AUTH_CHALLENGE":
				_handle_auth_challenge(frame)
			"RUNTIME_REGISTERED":
				_handle_registered(frame)
			"ERROR":
				_handle_error_control(frame)
		return
	if kind == "response" and not bool(frame.get("success", false)):
		var error: Dictionary = (
			frame.get("error", {}) if typeof(frame.get("error")) == TYPE_DICTIONARY else {}
		)
		_last_error = str(error.get("code", "INFRASTRUCTURE_ERROR"))
		runtime_failed.emit(_last_error, str(error.get("message", "")))


func _handle_auth_challenge(frame: Dictionary) -> void:
	var payload: Dictionary = (
		frame.get("payload", {}) if typeof(frame.get("payload")) == TYPE_DICTIONARY else {}
	)
	var challenge_id := str(payload.get("challenge_id", ""))
	var challenge := str(payload.get("challenge", ""))
	if challenge_id.is_empty() or challenge.is_empty():
		_fail("CONTRACT_INVALID", "认证挑战缺少必需字段")
		return
	_client.send_frame(EditorAuth.make_auth_response(
		challenge_id,
		challenge,
		_credentials.client_secret()
	))


func _handle_registered(frame: Dictionary) -> void:
	var payload: Dictionary = (
		frame.get("payload", {}) if typeof(frame.get("payload")) == TYPE_DICTIONARY else {}
	)
	var server_id := str(payload.get("runtime_instance_id", ""))
	if not server_id.is_empty() and server_id != _runtime_instance_id:
		_fail("CONTRACT_INVALID", "Runtime 实例标识不一致")
		return
	_phase = PHASE_REGISTERED
	_report_interval = maxf(
		0.5,
		float(payload.get("heartbeat_interval_seconds", REPORT_INTERVAL_SECONDS))
	)
	_elapsed = _report_interval
	_last_error = ""
	runtime_registered.emit(_runtime_instance_id)


func _handle_error_control(frame: Dictionary) -> void:
	var payload: Dictionary = (
		frame.get("payload", {}) if typeof(frame.get("payload")) == TYPE_DICTIONARY else {}
	)
	var code := str(payload.get("code", "INFRASTRUCTURE_ERROR"))
	_fail(code, str(payload.get("message", "")))
	# 端点返回 ERROR 表示不可恢复（认证失败、指纹不匹配等），停止重试。
	_client.close(4401, code)


func _on_connection_closed(code: int, reason: String, reconnect: bool) -> void:
	if _phase == PHASE_DISABLED:
		return
	_phase = PHASE_CONNECTING if reconnect else PHASE_ERROR
	if code >= 4400:
		_last_error = str(code)
		if not reason.is_empty():
			_last_error = "%s: %s" % [code, reason]
	_elapsed = 0.0
	_reconnect_elapsed = 0.0


func _on_protocol_error(code: String, message: String) -> void:
	_fail(code, message)


func _fail(code: String, message: String) -> void:
	_last_error = code
	_phase = PHASE_ERROR
	runtime_failed.emit(code, message)


func _tick_report(delta: float) -> void:
	if _phase != PHASE_REGISTERED:
		return
	_elapsed += delta
	if _elapsed < _report_interval:
		return
	_elapsed = 0.0
	_report(STATUS_RUNNING)


func _tick_reconnect(delta: float) -> void:
	if _phase != PHASE_CONNECTING:
		return
	if _client.is_open():
		return
	_reconnect_elapsed += delta
	if _reconnect_elapsed < RECONNECT_INTERVAL_SECONDS:
		return
	_reconnect_elapsed = 0.0
	_client.connect_to_backend()


func _report(status: String) -> String:
	if _client == null:
		return ""
	_request_counter += 1
	var frame := make_report_frame(_runtime_instance_id, status)
	frame["request_id"] = "req_rt%08x%02x" % [
		int(Time.get_ticks_usec()) & 0xFFFFFFFF,
		_request_counter & 0xFF,
	]
	var errors: Array = Validator.validate_request(frame)
	if not errors.is_empty():
		_fail("CONTRACT_INVALID", str(errors[0]))
		return ""
	_client.send_frame(frame, "EPHEMERAL" if status == STATUS_RUNNING else "PERSISTENT")
	return str(frame["request_id"])
