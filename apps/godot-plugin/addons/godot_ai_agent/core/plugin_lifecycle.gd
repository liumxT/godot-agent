@tool
extends RefCounted
## 插件生命周期状态机（E3-T01）。
##
## 状态迁移：
##   DISABLED → ENABLING → INITIALIZING → READY → DISABLING → DISABLED
##   INITIALIZING / READY → ERROR → DISABLING → DISABLED
##
## 本类只负责编排：读取配置、校验版本、构建上下文、注册并启动服务、
## 注册/释放 Dock。`plugin.gd` 仅做转发，不包含通信细节。


const PluginLog := preload("res://addons/godot_ai_agent/core/logger.gd")
const PluginContextScript := preload("res://addons/godot_ai_agent/core/plugin_context.gd")
const ServiceRegistryScript := preload("res://addons/godot_ai_agent/core/service_registry.gd")
const ServiceBase := preload("res://addons/godot_ai_agent/core/service.gd")
const StatusPanel := preload("res://addons/godot_ai_agent/ui/status_panel.gd")
const ConnectionPanel := preload("res://addons/godot_ai_agent/ui/connection_panel.gd")
const EditorSessionService := preload("res://addons/godot_ai_agent/services/editor_session_service.gd")
const HeartbeatService := preload("res://addons/godot_ai_agent/services/heartbeat_service.gd")
const EventSyncService := preload("res://addons/godot_ai_agent/services/event_sync_service.gd")
const EditorStateProvider := preload("res://addons/godot_ai_agent/state/editor_state_provider.gd")
const SnapshotService := preload("res://addons/godot_ai_agent/services/snapshot_service.gd")
const ReconnectionService := preload("res://addons/godot_ai_agent/services/reconnection_service.gd")

const SESSION_SERVICE_NAME := "editor_session_service"
const HEARTBEAT_SERVICE_NAME := "heartbeat_service"
const EVENT_SERVICE_NAME := "event_sync_service"
const STATE_PROVIDER_SERVICE_NAME := "editor_state_provider"
const SNAPSHOT_SERVICE_NAME := "snapshot_service"
const RECONNECTION_SERVICE_NAME := "reconnection_service"

const STATE_DISABLED := "DISABLED"
const STATE_ENABLING := "ENABLING"
const STATE_INITIALIZING := "INITIALIZING"
const STATE_READY := "READY"
const STATE_DISABLING := "DISABLING"
const STATE_ERROR := "ERROR"

const MIN_GODOT_MAJOR := 4
const MIN_GODOT_MINOR := 5

const ERROR_UNSUPPORTED_VERSION := "UNSUPPORTED_GODOT_VERSION"
const ERROR_SERVICE_REGISTRATION := "SERVICE_REGISTRATION_FAILED"
const ERROR_SERVICE_START := "SERVICE_START_FAILED"


var _state := STATE_DISABLED
var _error_code := ""
var _detail := ""
var _plugin_version := ""
var _godot_version := ""
var _host: Object = null
var _dock_slot := 0
var _dock: Control = null
var _connection_panel: Control = null
var _with_default_services := false
var _context: Object = null
var _registry: Object = null
var _pending_services: Array = []


## 在 enable() 之前登记服务，服务名与依赖顺序由注册表处理。
func add_service(name: String, service: Object, dependencies: Array = []) -> bool:
	if _state != STATE_DISABLED:
		PluginLog.error("service_add_rejected", {
			"service": name,
			"status": _state,
		})
		return false
	if name.is_empty() or service == null:
		PluginLog.error("service_add_rejected", {
			"service": name,
			"reason": "invalid_service",
		})
		return false
	for entry in _pending_services:
		if entry["name"] == name:
			PluginLog.warn("service_add_duplicate", {"service": name})
			return false
	_pending_services.append({
		"name": name,
		"service": service,
		"dependencies": dependencies.duplicate(),
	})
	return true


func enable(
	host: Object = null,
	dock_slot: int = 0,
	plugin_version: String = "0.0.0",
	with_default_services: bool = false
) -> bool:
	if _state != STATE_DISABLED:
		PluginLog.warn("plugin_enable_rejected", {"status": _state})
		return false

	_state = STATE_ENABLING
	_host = host
	_dock_slot = dock_slot
	_plugin_version = plugin_version
	_with_default_services = with_default_services
	_error_code = ""
	_detail = ""
	PluginLog.info("plugin_enabling", {"version": plugin_version})

	var version := Engine.get_version_info()
	_godot_version = str(version.get("string", "unknown"))
	_context = PluginContextScript.new(_host, _plugin_version, _godot_version)

	_state = STATE_INITIALIZING
	if not _is_supported_godot(version):
		_enter_error(ERROR_UNSUPPORTED_VERSION, "需要 Godot %d.%d+" % [
			MIN_GODOT_MAJOR, MIN_GODOT_MINOR,
		])
		return false

	_registry = ServiceRegistryScript.new(_context)
	_context.call("set_config", "service_registry", _registry)
	if with_default_services:
		_register_default_services()
	for entry in _pending_services:
		if not bool(_registry.call("register", entry["name"], entry["service"], entry["dependencies"])):
			_enter_error(ERROR_SERVICE_REGISTRATION, "服务注册失败：%s" % str(entry["name"]))
			return false

	if not bool(_registry.call("start_all")):
		_enter_error(ERROR_SERVICE_START, _first_failure_detail())
		return false

	_ensure_dock()
	_state = STATE_READY
	_update_dock()
	PluginLog.info("plugin_ready", {"version": _plugin_version})
	return true


## 关闭顺序与启动逆序一致：停止服务 → 释放 Dock → 清空上下文。
## 单步失败只记录日志，不阻塞后续清理。
func disable(reason: String = "disabled") -> void:
	if _state == STATE_DISABLED or _state == STATE_DISABLING:
		return

	_state = STATE_DISABLING
	_update_dock()

	if _registry != null:
		_registry.call("stop_all", reason)
	_registry = null

	_release_dock()
	if _context != null:
		_context.call("release")
	_context = null
	_host = null

	_error_code = ""
	_detail = ""
	_state = STATE_DISABLED
	PluginLog.info("plugin_disabled", {"reason": reason})


func tick(delta: float) -> void:
	if _state != STATE_READY or _registry == null:
		return
	_registry.call("tick", delta)
	_update_connection_panel()


func get_state() -> String:
	return _state


func get_context() -> Object:
	return _context


func status() -> Dictionary:
	return {
		"state": _state,
		"error_code": _error_code,
		"detail": _detail,
		"plugin_version": _plugin_version,
	}


func _enter_error(error_code: String, detail: String) -> void:
	_error_code = error_code
	_detail = detail
	_state = STATE_ERROR
	_ensure_dock()
	_update_dock()
	PluginLog.error("plugin_error", {
		"error_code": error_code,
		"detail": detail,
	})


func _first_failure_detail() -> String:
	if _registry == null:
		return "服务注册表不可用"
	var snapshot_value: Variant = _registry.call("snapshot")
	if typeof(snapshot_value) != TYPE_DICTIONARY:
		return "服务启动失败"
	var snapshot: Dictionary = snapshot_value
	var services: Dictionary = snapshot.get("services", {})
	for name in snapshot.get("order", []):
		var info: Dictionary = services.get(str(name), {})
		var state := str(info.get("state", ""))
		if state == ServiceBase.STATE_FAILED or state == ServiceBase.STATE_BLOCKED:
			return "%s: %s" % [
				str(name),
				str(info.get("error_code", "SERVICE_UNAVAILABLE")),
			]
	return "服务启动失败"


func _is_supported_godot(version: Dictionary) -> bool:
	var major := int(version.get("major", 0))
	var minor := int(version.get("minor", 0))
	return major == MIN_GODOT_MAJOR and minor >= MIN_GODOT_MINOR


func _ensure_dock() -> void:
	if _dock != null and is_instance_valid(_dock):
		_update_dock()
		return
	if _host == null or not _host.has_method("add_control_to_dock"):
		return
	_dock = StatusPanel.new()
	_dock.call("set_godot_version", _godot_version)
	_dock.call("set_backend_status", "未连接")
	_host.call("add_control_to_dock", _dock_slot, _dock)
	if _with_default_services:
		_ensure_connection_panel()
	_update_dock()


func _ensure_connection_panel() -> void:
	if _connection_panel != null and is_instance_valid(_connection_panel):
		return
	_connection_panel = ConnectionPanel.new()
	_connection_panel.connect("connect_requested", _on_connect_requested)
	_connection_panel.connect("disconnect_requested", _on_disconnect_requested)
	_host.call("add_control_to_dock", _dock_slot, _connection_panel)
	_update_connection_panel()


func _release_dock() -> void:
	if _connection_panel != null:
		if is_instance_valid(_connection_panel):
			if _host != null and _host.has_method("remove_control_from_docks"):
				_host.call("remove_control_from_docks", _connection_panel)
			_connection_panel.queue_free()
		_connection_panel = null
	if _dock == null:
		return
	if is_instance_valid(_dock):
		if _host != null and _host.has_method("remove_control_from_docks"):
			_host.call("remove_control_from_docks", _dock)
		_dock.queue_free()
	_dock = null


func _update_dock() -> void:
	if _dock == null or not is_instance_valid(_dock):
		return
	var text := "未启用"
	match _state:
		STATE_ENABLING, STATE_INITIALIZING:
			text = "初始化中"
		STATE_READY:
			text = "已启用 v%s" % _plugin_version
		STATE_DISABLING:
			text = "关闭中"
		STATE_ERROR:
			text = "错误：%s" % _error_code
	_dock.call("set_plugin_status", text)
	_update_connection_panel()


func _register_default_services() -> void:
	_register_default(SESSION_SERVICE_NAME, EditorSessionService, [])
	_register_default(HEARTBEAT_SERVICE_NAME, HeartbeatService, [SESSION_SERVICE_NAME])
	_register_default(EVENT_SERVICE_NAME, EventSyncService, [SESSION_SERVICE_NAME])
	_register_default(
		STATE_PROVIDER_SERVICE_NAME,
		EditorStateProvider,
		[SESSION_SERVICE_NAME]
	)
	_register_default(
		SNAPSHOT_SERVICE_NAME,
		SnapshotService,
		[SESSION_SERVICE_NAME, EVENT_SERVICE_NAME, STATE_PROVIDER_SERVICE_NAME]
	)
	_register_default(
		RECONNECTION_SERVICE_NAME,
		ReconnectionService,
		[SESSION_SERVICE_NAME, EVENT_SERVICE_NAME, SNAPSHOT_SERVICE_NAME]
	)


func _register_default(name: String, script: Script, dependencies: Array) -> void:
	for entry in _pending_services:
		if entry["name"] == name:
			return
	_pending_services.append({
		"name": name,
		"service": script.new(),
		"dependencies": dependencies.duplicate(),
	})


func _session_service() -> Object:
	if _registry == null:
		return null
	return _registry.call("get_service", SESSION_SERVICE_NAME)


func _update_connection_panel() -> void:
	if _connection_panel == null or not is_instance_valid(_connection_panel):
		return
	var service := _session_service()
	if service == null or not service.has_method("status"):
		return
	_connection_panel.call("render", service.call("status"))


func _on_connect_requested() -> void:
	var service := _session_service()
	if service != null and service.has_method("request_connect"):
		service.call("request_connect")
	_update_connection_panel()


func _on_disconnect_requested() -> void:
	var service := _session_service()
	if service != null and service.has_method("request_disconnect"):
		service.call("request_disconnect")
	_update_connection_panel()
