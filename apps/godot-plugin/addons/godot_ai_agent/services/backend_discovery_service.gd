@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## Backend Discovery 服务（E3-T03）。
##
## 地址优先级：EditorSettings → 环境变量 GODOT_AI_BACKEND_URL → 插件默认值。
## 只允许回环地址；通过 /api/v1/health/live 与 /api/v1/system/info 判断状态。
## 传输层使用 StreamPeerTCP 手写最小 HTTP/1.1 请求，避免依赖 HTTPClient 的帧内推进；
## 所有网络操作在 tick 中非阻塞推进，失败按退避重试。


signal result_changed(result: String, detail: Dictionary)

const Backoff := preload("res://addons/godot_ai_agent/utilities/backoff.gd")

const RESULT_NOT_STARTED := "BACKEND_NOT_STARTED"
const RESULT_STARTING := "BACKEND_STARTING"
const RESULT_READY := "BACKEND_READY"
const RESULT_INCOMPATIBLE := "BACKEND_INCOMPATIBLE"
const RESULT_UNREACHABLE := "BACKEND_UNREACHABLE"
const RESULT_INVALID_URL := "BACKEND_INVALID_URL"

const DEFAULT_BACKEND_URL := "http://127.0.0.1:8765"
const ENV_BACKEND_URL := "GODOT_AI_BACKEND_URL"
const EDITOR_SETTINGS_KEY := "godot_ai_agent/backend_url"
const HEALTH_PATH := "/api/v1/health/live"
const INFO_PATH := "/api/v1/system/info"
const API_VERSION := "v1"
const PROTOCOL_MAJOR_PREFIX := "1."
const PROBE_BUDGET_MS := 3000
const MAX_RESPONSE_BYTES := 65536

const STATUS_REFUSED := -1
const STATUS_UNREACHABLE := -2

const PHASE_IDLE := "IDLE"
const PHASE_WAIT := "WAIT"
const PHASE_CONNECTING := "CONNECTING"
const PHASE_HEALTH := "HEALTH"
const PHASE_INFO := "INFO"
const PHASE_DONE := "DONE"

var _backend_url := DEFAULT_BACKEND_URL
var _result := ""
var _result_detail: Dictionary = {}
var _phase := PHASE_IDLE
var _peer: StreamPeerTCP = null
var _rx := PackedByteArray()
var _host := ""
var _port := 0
var _request_path := ""
var _waiting_phase := PHASE_HEALTH
var _attempt_started_ms := 0
var _retry_at_ms := 0
var _backoff: RefCounted = null


func _initialize() -> bool:
	_backend_url = resolve_backend_url(
		_read_settings_url(),
		OS.get_environment(ENV_BACKEND_URL),
		_default_url()
	)
	_backoff = Backoff.new()
	return true


func _start() -> bool:
	_phase = PHASE_IDLE
	_begin_attempt()
	return true


func _tick(_delta: float) -> void:
	match _phase:
		PHASE_WAIT:
			if Time.get_ticks_msec() >= _retry_at_ms:
				_begin_attempt()
		PHASE_CONNECTING:
			_poll_connect()
		PHASE_HEALTH, PHASE_INFO:
			_poll_probe()


func _stop(_reason: String) -> void:
	_release_peer()
	_phase = PHASE_IDLE


func _dispose() -> void:
	_release_peer()


func get_backend_url() -> String:
	return _backend_url


func set_backend_url(url: String) -> void:
	_backend_url = url.strip_edges()


func get_result() -> String:
	return _result


func get_result_detail() -> Dictionary:
	return _result_detail.duplicate(true)


func get_phase() -> String:
	return _phase


## 用户点击「连接」时调用：重置退避并立即重新探测。
func trigger_retry() -> void:
	if _backoff != null:
		_backoff.reset()
	if is_running():
		_begin_attempt()


static func resolve_backend_url(settings_url: String, env_url: String, default_url: String) -> String:
	if not settings_url.strip_edges().is_empty():
		return settings_url.strip_edges()
	if not env_url.strip_edges().is_empty():
		return env_url.strip_edges()
	return default_url.strip_edges()


static func parse_http_url(url: String) -> Dictionary:
	var text := url.strip_edges()
	if not text.begins_with("http://"):
		return {"ok": false, "reason": "scheme"}
	var rest := text.substr("http://".length())
	var slash := rest.find("/")
	var authority := rest if slash == -1 else rest.substr(0, slash)
	if authority.is_empty():
		return {"ok": false, "reason": "host"}
	var host := authority
	var port := 80
	var colon := authority.rfind(":")
	if colon != -1:
		host = authority.substr(0, colon)
		var port_text := authority.substr(colon + 1)
		if not port_text.is_valid_int():
			return {"ok": false, "reason": "port"}
		port = int(port_text)
		if port <= 0 or port > 65535:
			return {"ok": false, "reason": "port"}
	if host.is_empty():
		return {"ok": false, "reason": "host"}
	return {"ok": true, "host": host, "port": port}


static func is_loopback_url(url: String) -> bool:
	var parsed := parse_http_url(url)
	if not bool(parsed.get("ok", false)):
		return false
	var host := str(parsed["host"]).to_lower()
	return host == "127.0.0.1" or host == "localhost"


static func classify_probe(
	live_status: int,
	info_status: int,
	api_version: String,
	protocol_version: String
) -> String:
	if live_status == STATUS_REFUSED:
		return RESULT_NOT_STARTED
	if live_status == STATUS_UNREACHABLE:
		return RESULT_UNREACHABLE
	if live_status != 200:
		return RESULT_STARTING
	if info_status != 200:
		return RESULT_STARTING
	if api_version != API_VERSION:
		return RESULT_INCOMPATIBLE
	if not protocol_version.begins_with(PROTOCOL_MAJOR_PREFIX):
		return RESULT_INCOMPATIBLE
	return RESULT_READY


func _default_url() -> String:
	if context != null and context.has_method("get_config"):
		return str(context.call("get_config", "backend_url", DEFAULT_BACKEND_URL))
	return DEFAULT_BACKEND_URL


func _read_settings_url() -> String:
	if context == null or not context.has_method("get_editor_interface"):
		return ""
	var editor_interface: Object = context.call("get_editor_interface")
	if editor_interface == null or not editor_interface.has_method("get_editor_settings"):
		return ""
	var settings: Object = editor_interface.call("get_editor_settings")
	if settings == null:
		return ""
	if settings.has_method("has_setting") and bool(settings.call("has_setting", EDITOR_SETTINGS_KEY)):
		return str(settings.call("get_setting", EDITOR_SETTINGS_KEY, ""))
	return ""


func _begin_attempt() -> void:
	_release_peer()
	_response_reset()
	_result = ""
	_result_detail = {}

	if not is_loopback_url(_backend_url):
		_finish(RESULT_INVALID_URL, {"url": _backend_url})
		return
	var parsed := parse_http_url(_backend_url)
	if not bool(parsed.get("ok", false)):
		_finish(RESULT_INVALID_URL, {"url": _backend_url})
		return

	_host = str(parsed["host"])
	_port = int(parsed["port"])
	_attempt_started_ms = Time.get_ticks_msec()
	_open_request(HEALTH_PATH, PHASE_HEALTH)


## 建立新连接并登记本次请求；连接成功后由 _poll_connect 发送请求。
func _open_request(path: String, waiting_phase: String) -> void:
	_release_peer()
	_response_reset()
	_request_path = path
	_waiting_phase = waiting_phase
	_peer = StreamPeerTCP.new()
	var err := _peer.connect_to_host(_host, _port)
	if err != OK:
		_on_connect_failed()
		return
	_phase = PHASE_CONNECTING


func _poll_connect() -> void:
	if _peer == null:
		_finish(RESULT_UNREACHABLE, {"reason": "peer_missing"})
		return
	_peer.poll()
	var status := _peer.get_status()
	if status == StreamPeerTCP.STATUS_CONNECTED:
		var request := "GET %s HTTP/1.1\r\nHost: %s:%d\r\nAccept: application/json\r\nConnection: close\r\n\r\n" % [
			_request_path, _host, _port,
		]
		if _peer.put_data(request.to_utf8_buffer()) != OK:
			_finish(RESULT_UNREACHABLE, {"reason": "request_write"})
			return
		_phase = _waiting_phase
		return
	if status == StreamPeerTCP.STATUS_ERROR:
		_on_connect_failed()
		return
	if _expired():
		_finish(RESULT_UNREACHABLE, {"reason": "connect_timeout"})


## 连接失败：健康探测阶段视为未启动，后续探测阶段视为探测中途断开。
func _on_connect_failed() -> void:
	if _waiting_phase == PHASE_HEALTH:
		_finish(RESULT_NOT_STARTED, {"reason": "connection_refused"})
	else:
		_finish(RESULT_STARTING, {"reason": "connection_lost"})


func _poll_probe() -> void:
	if _peer == null:
		_finish(RESULT_UNREACHABLE, {"reason": "peer_missing"})
		return
	_peer.poll()
	var status := _peer.get_status()
	if status == StreamPeerTCP.STATUS_CONNECTED or status == StreamPeerTCP.STATUS_NONE:
		var available := _peer.get_available_bytes()
		if available > 0:
			var chunk: Array = _peer.get_data(available)
			if int(chunk[0]) == OK:
				_rx.append_array(chunk[1])
		if _rx.size() > MAX_RESPONSE_BYTES:
			_finish(RESULT_UNREACHABLE, {"reason": "response_too_large"})
			return
		var response := _try_parse_response()
		if not response.is_empty():
			_handle_response(int(response["status"]), str(response["body"]))
			return
	if status == StreamPeerTCP.STATUS_ERROR:
		_finish(RESULT_STARTING, {"reason": "closed_during_probe"})
		return
	if _expired():
		_finish(RESULT_UNREACHABLE, {"reason": "timeout"})


## 解析已完成的最小 HTTP/1.1 响应；数据不足时返回空字典。
func _try_parse_response() -> Dictionary:
	var header_end := _find_header_end()
	if header_end == -1:
		return {}
	var header_text := _rx.slice(0, header_end).get_string_from_utf8()
	var lines := header_text.split("\r\n")
	if lines.is_empty():
		return {}
	var status_parts := str(lines[0]).split(" ")
	if status_parts.size() < 2 or not str(status_parts[1]).is_valid_int():
		return {}
	var content_length := 0
	for index in range(1, lines.size()):
		var line := str(lines[index])
		var colon := line.find(":")
		if colon <= 0:
			continue
		if line.substr(0, colon).strip_edges().to_lower() == "content-length":
			var value := line.substr(colon + 1).strip_edges()
			if value.is_valid_int():
				content_length = int(value)
	var body := _rx.slice(header_end + 4)
	if body.size() < content_length:
		return {}
	return {
		"status": int(status_parts[1]),
		"body": body.slice(0, content_length).get_string_from_utf8(),
	}


func _find_header_end() -> int:
	for index in range(0, _rx.size() - 3):
		if (
			_rx[index] == 13
			and _rx[index + 1] == 10
			and _rx[index + 2] == 13
			and _rx[index + 3] == 10
		):
			return index
	return -1


func _handle_response(code: int, body: String) -> void:
	if _waiting_phase == PHASE_HEALTH:
		if code != 200:
			_finish(RESULT_STARTING, {"reason": "health_not_ready", "http_status": code})
			return
		_open_request(INFO_PATH, PHASE_INFO)
		return

	if code != 200:
		_finish(RESULT_STARTING, {"reason": "info_not_ready", "http_status": code})
		return
	var parsed: Variant = JSON.parse_string(body)
	if typeof(parsed) != TYPE_DICTIONARY:
		_finish(RESULT_INCOMPATIBLE, {"reason": "system_info_not_json"})
		return
	var api_version := str(parsed.get("api_version", ""))
	var protocol_version := str(parsed.get("protocol_version", ""))
	var result := classify_probe(200, code, api_version, protocol_version)
	_finish(result, {
		"api_version": api_version,
		"protocol_version": protocol_version,
	})


func _finish(result: String, detail: Dictionary = {}) -> void:
	_release_peer()
	_response_reset()
	_result = result
	_result_detail = detail.duplicate(true)

	if result == RESULT_READY:
		_phase = PHASE_DONE
		if _backoff != null:
			_backoff.reset()
	elif result == RESULT_INVALID_URL:
		_phase = PHASE_DONE
	else:
		_phase = PHASE_WAIT
		var delay := 1.0 if _backoff == null else float(_backoff.next_delay())
		_retry_at_ms = Time.get_ticks_msec() + int(delay * 1000.0)

	result_changed.emit(result, _result_detail)


func _expired() -> bool:
	return Time.get_ticks_msec() - _attempt_started_ms > PROBE_BUDGET_MS


func _response_reset() -> void:
	_rx = PackedByteArray()


func _release_peer() -> void:
	if _peer != null:
		_peer.disconnect_from_host()
		_peer = null
	_response_reset()
