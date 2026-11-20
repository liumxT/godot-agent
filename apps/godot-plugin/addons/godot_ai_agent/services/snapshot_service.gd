@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## 快照服务（E3-T11）。
##
## 只采集摘要字段，不读取资源内容；生成后先按契约校验再提交。
## ``snapshot_version`` 每次采集递增，``last_event_sequence`` 取事件同步进度。

signal snapshot_captured(snapshot: Dictionary)
signal snapshot_stored(snapshot: Dictionary)
signal snapshot_received(snapshot: Dictionary)
signal snapshot_failed(code: String, message: String)

const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")

const SERVICE_NAME := "snapshot_service"
const SESSION_SERVICE_NAME := "editor_session_service"
const EVENT_SERVICE_NAME := "event_sync_service"
const STATE_PROVIDER_SERVICE_NAME := "editor_state_provider"

const MAX_SELECTION := 64

var _session: Object = null
var _event_sync: Object = null
var _state_provider: Object = null
var _version := 0
var _last_snapshot: Dictionary = {}
var _last_error := ""
var _in_flight_submit := 0


func _initialize() -> bool:
	_version = int(context.get_config("snapshot_version_start", 0))
	_attach_from_registry()
	return true


func _start() -> bool:
	if _session == null:
		_attach_from_registry()
	if _session != null:
		_bind_session()
	return true


func _stop(_reason: String) -> void:
	_unbind_session()
	_in_flight_submit = 0


func _dispose() -> void:
	_session = null
	_event_sync = null
	_state_provider = null
	_last_snapshot.clear()


func attach_session(session: Object) -> void:
	if _session == session:
		return
	_unbind_session()
	_session = session
	if _session != null and _state == STATE_RUNNING:
		_bind_session()


func attach_event_sync(service: Object) -> void:
	_event_sync = service


## 快照复用状态采集结果，避免两处实现产生不一致的 Editor 状态。
func attach_state_provider(service: Object) -> void:
	_state_provider = service


## 采集当前编辑器摘要；失败返回空字典并触发 snapshot_failed。
func capture() -> Dictionary:
	if _session == null:
		_last_error = "SESSION_UNAVAILABLE"
		snapshot_failed.emit(_last_error, "会话未建立")
		return {}
	var data: Dictionary = _session.call("session_data")
	var session_id := str(data.get("session_id", ""))
	if session_id.is_empty():
		_last_error = "SESSION_UNAVAILABLE"
		snapshot_failed.emit(_last_error, "会话未建立")
		return {}
	_version += 1
	var state := _collect_editor_state()
	var snapshot := {
		"snapshot_id": _snapshot_id(session_id, _version),
		"session_id": session_id,
		"project_id": str(data.get("project_id", "")),
		"editor_instance_id": str(data.get("editor_instance_id", "")),
		"snapshot_version": _version,
		"last_event_sequence": _event_sequence(),
		"created_at": _timestamp(),
		"editor_status": str(state.get("editor_status", "UNKNOWN")),
		"project_status": str(state.get("project_status", "MISSING")),
		"active_scene": state.get("active_scene", null),
		"current_selection": (state.get("current_selection", []) as Array).duplicate(),
		"unsaved_resources": (state.get("unsaved_resources", []) as Array).duplicate(true),
		"run_status": str(state.get("run_status", "STOPPED")),
		"import_status": str(state.get("import_status", "IDLE")),
		"truncated": false,
	}
	var errors: Array = Validator.validate_bridge_snapshot(snapshot)
	if not errors.is_empty():
		_last_error = str(errors[0])
		snapshot_failed.emit("CONTRACT_INVALID", _last_error)
		return {}
	_last_snapshot = snapshot.duplicate(true)
	snapshot_captured.emit(snapshot.duplicate(true))
	return snapshot


## 采集并提交快照；返回 request_id。
func submit() -> String:
	if _session == null or not bool(_session.call("is_session_connected")):
		return ""
	var snapshot := capture()
	if snapshot.is_empty():
		return ""
	var request_id := str(_session.call(
		"send_request", "editor.snapshot", snapshot, "PERSISTENT"
	))
	if not request_id.is_empty():
		_in_flight_submit += 1
	return request_id


## 拉取 Backend 保存的最新快照；返回 request_id。
func request_latest() -> String:
	if _session == null or not bool(_session.call("is_session_connected")):
		return ""
	return str(_session.call("send_request", "editor.snapshot", {}, "PERSISTENT"))


func latest_snapshot() -> Dictionary:
	return _last_snapshot.duplicate(true)


func status() -> Dictionary:
	var base: Dictionary = super.status()
	base["version"] = _version
	base["snapshot_id"] = str(_last_snapshot.get("snapshot_id", ""))
	base["error_code"] = _last_error
	return base


func _attach_from_registry() -> void:
	var registry: Variant = context.get_config("service_registry", null)
	if registry == null:
		return
	if _session == null:
		_session = registry.call("get_service", SESSION_SERVICE_NAME)
	if _event_sync == null:
		_event_sync = registry.call("get_service", EVENT_SERVICE_NAME)
	if _state_provider == null:
		_state_provider = registry.call("get_service", STATE_PROVIDER_SERVICE_NAME)


func _bind_session() -> void:
	if _session == null:
		return
	if not _session.is_connected("response_received", _on_response):
		_session.connect("response_received", _on_response)


func _unbind_session() -> void:
	if _session == null:
		return
	if _session.is_connected("response_received", _on_response):
		_session.disconnect("response_received", _on_response)


func _on_response(action: String, response: Dictionary) -> void:
	if action != "editor.snapshot":
		return
	if not bool(response.get("success", false)):
		var error: Dictionary = (
			response.get("error", {}) if typeof(response.get("error")) == TYPE_DICTIONARY else {}
		)
		_last_error = str(error.get("code", "SNAPSHOT_UNAVAILABLE"))
		_in_flight_submit = 0
		snapshot_failed.emit(_last_error, str(error.get("message", "")))
		return
	var data: Dictionary = (
		response.get("data", {}) if typeof(response.get("data")) == TYPE_DICTIONARY else {}
	)
	var snapshot: Variant = data.get("snapshot", {})
	if typeof(snapshot) != TYPE_DICTIONARY:
		return
	var errors: Array = Validator.validate_bridge_snapshot(snapshot)
	if not errors.is_empty():
		_last_error = str(errors[0])
		snapshot_failed.emit("CONTRACT_INVALID", _last_error)
		return
	_last_snapshot = (snapshot as Dictionary).duplicate(true)
	if _in_flight_submit > 0:
		_in_flight_submit -= 1
		snapshot_stored.emit(_last_snapshot.duplicate(true))
	snapshot_received.emit(_last_snapshot.duplicate(true))


func _snapshot_id(session_id: String, version: int) -> String:
	return "snp_%012x" % (
		(hash(session_id) ^ (version * 2654435761) ^ int(Time.get_ticks_usec())) & 0xFFFFFFFFFFFF
	)


func _event_sequence() -> int:
	if _event_sync == null:
		return 0
	return int(_event_sync.call("last_sequence"))


## 优先复用状态采集服务；未注册时回退到本地采集，保证独立可用。
func _collect_editor_state() -> Dictionary:
	if _state_provider != null and _state_provider.has_method("collect"):
		var value: Variant = _state_provider.call("collect")
		if typeof(value) == TYPE_DICTIONARY and not (value as Dictionary).is_empty():
			return (value as Dictionary).duplicate(true)
	return {
		"editor_status": _editor_status(),
		"project_status": _project_status(),
		"active_scene": _active_scene(),
		"current_selection": _current_selection(),
		"unsaved_resources": [],
		"run_status": _run_status(),
		"import_status": "IDLE",
	}


func _editor_interface() -> Object:
	return context.get_editor_interface()


func _editor_status() -> String:
	var override := str(context.get_config("editor_status_override", ""))
	if not override.is_empty():
		return override
	return "UNKNOWN" if _editor_interface() == null else "READY"


func _project_status() -> String:
	var override := str(context.get_config("project_status_override", ""))
	if not override.is_empty():
		return override
	return "READY" if FileAccess.file_exists("res://project.godot") else "MISSING"


func _active_scene() -> Variant:
	var iface := _editor_interface()
	if iface == null or not iface.has_method("get_edited_scene_root"):
		return null
	var root: Variant = iface.call("get_edited_scene_root")
	if root == null:
		return null
	var path := str(root.get("scene_file_path"))
	return path if not path.is_empty() else null


func _current_selection() -> Array:
	var iface := _editor_interface()
	if iface == null or not iface.has_method("get_selection"):
		return []
	var selection: Variant = iface.call("get_selection")
	if selection == null or not selection.has_method("get_selected_nodes"):
		return []
	var result: Array = []
	for node in selection.call("get_selected_nodes"):
		if node == null:
			continue
		var path := str(node.get_path())
		if not path.is_empty():
			result.append(path)
		if result.size() >= MAX_SELECTION:
			break
	return result


func _run_status() -> String:
	var override := str(context.get_config("run_status_override", ""))
	if not override.is_empty():
		return override
	var iface := _editor_interface()
	if iface != null and iface.has_method("is_playing_scene") and bool(iface.call("is_playing_scene")):
		return "RUNNING"
	return "STOPPED"


func _timestamp() -> String:
	return Time.get_datetime_string_from_unix_time(
		int(Time.get_unix_time_from_system())
	) + "Z"
