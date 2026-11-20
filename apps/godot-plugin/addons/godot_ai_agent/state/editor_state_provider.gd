@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## 编辑器状态采集（E3-T15）。
##
## 只采集 Godot Editor 可观测的事实：Editor 状态、项目状态、活动场景、当前选中、
## 未保存资源摘要、运行状态与导入状态。状态是否生效由 Backend 判定，本服务
## 不写盘、不缓存业务数据，同一状态不重复上报。

signal state_collected(state: Dictionary)
signal state_reported(changed: Array, request_id: String)
signal report_failed(code: String, message: String)

const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")

const SERVICE_NAME := "editor_state_provider"
const SESSION_SERVICE_NAME := "editor_session_service"
const REPORT_ACTION := "editor.state.report"

## 字段顺序固定，便于 diff 结果稳定与测试断言。
const STATE_FIELDS := [
	"editor_status",
	"project_status",
	"active_scene",
	"current_selection",
	"unsaved_resources",
	"run_status",
	"import_status",
]
const FIELD_SELECTION := "current_selection"
const DELIVERY_EPHEMERAL := "EPHEMERAL"
const DELIVERY_PERSISTENT := "PERSISTENT"

const MAX_SELECTION := 64
const MAX_SELECTION_PATH := 512
const MAX_UNSAVED := 500
const MAX_RESOURCE_PATH := 1024
const DEFAULT_MIN_INTERVAL_SECONDS := 1.0

var _session: Object = null
var _min_interval := DEFAULT_MIN_INTERVAL_SECONDS
var _elapsed := 0.0
var _last_state: Dictionary = {}
var _last_reported: Dictionary = {}
var _last_error := ""
var _last_request_id := ""
var _report_count := 0


func _initialize() -> bool:
	_min_interval = maxf(
		0.05,
		float(context.get_config("state_report_min_interval_seconds", DEFAULT_MIN_INTERVAL_SECONDS))
	)
	_attach_from_registry()
	return true


func _start() -> bool:
	if _session == null:
		_attach_from_registry()
	if _session != null:
		_bind_session()
	# 会话建立后第一帧即可上报，避免等待一个完整周期。
	_elapsed = _min_interval
	return true


func _stop(_reason: String) -> void:
	_unbind_session()
	_elapsed = 0.0


func _dispose() -> void:
	_session = null
	_last_state.clear()
	_last_reported.clear()


func _tick(delta: float) -> void:
	_elapsed += delta
	if _elapsed < _min_interval:
		return
	_elapsed = 0.0
	if _session == null or not bool(_session.call("is_session_connected")):
		return
	report()


## 采集当前编辑器状态；字段缺失或不可判定时回退到安全默认值。
func collect() -> Dictionary:
	var override: Variant = context.get_config("state_override", null)
	if typeof(override) == TYPE_DICTIONARY and not (override as Dictionary).is_empty():
		var overridden := _normalize(override as Dictionary)
		_last_state = overridden.duplicate(true)
		state_collected.emit(_last_state.duplicate(true))
		return overridden
	var state := _normalize({
		"editor_status": _editor_status(),
		"project_status": _project_status(),
		"active_scene": _active_scene(),
		"current_selection": _current_selection(),
		"unsaved_resources": _unsaved_resources(),
		"run_status": _run_status(),
		"import_status": _import_status(),
	})
	_last_state = state.duplicate(true)
	state_collected.emit(_last_state.duplicate(true))
	return state


## 采集并与上次成功上报对比，只发送变化字段；返回 request_id。
## ``force`` 为 true 时即使无变化也上报（用于恢复后的首次同步）。
func report(force: bool = false) -> String:
	if _session == null or not bool(_session.call("is_session_connected")):
		return ""
	var state := collect()
	var errors: Array = Validator.validate_bridge_editor_state(state)
	if not errors.is_empty():
		_last_error = str(errors[0])
		report_failed.emit("CONTRACT_INVALID", _last_error)
		return ""
	var changed: Array = STATE_FIELDS.duplicate() if _last_reported.is_empty() \
		else changed_fields(_last_reported, state)
	if changed.is_empty() and not force:
		return ""
	if changed.is_empty():
		changed = STATE_FIELDS.duplicate()
	var payload: Dictionary = state.duplicate(true)
	payload["changed"] = changed
	var delivery := DELIVERY_EPHEMERAL \
		if changed.size() == 1 and str(changed[0]) == FIELD_SELECTION \
		else DELIVERY_PERSISTENT
	var request_id := str(_session.call("send_request", REPORT_ACTION, payload, delivery))
	if request_id.is_empty():
		return ""
	_last_reported = state.duplicate(true)
	_last_request_id = request_id
	_last_error = ""
	_report_count += 1
	state_reported.emit(changed.duplicate(), request_id)
	return request_id


## 计算两个状态之间的变化字段，顺序与 STATE_FIELDS 一致。
static func changed_fields(previous: Dictionary, current: Dictionary) -> Array:
	var result: Array = []
	for name in STATE_FIELDS:
		if previous.get(name) != current.get(name):
			result.append(name)
	return result


func latest_state() -> Dictionary:
	return _last_state.duplicate(true)


func status() -> Dictionary:
	var base: Dictionary = super.status()
	base["report_count"] = _report_count
	base["last_request_id"] = _last_request_id
	base["error_code"] = _last_error
	return base


func _attach_from_registry() -> void:
	var registry: Variant = context.get_config("service_registry", null)
	if registry == null:
		return
	if _session == null:
		_session = registry.call("get_service", SESSION_SERVICE_NAME)


func _bind_session() -> void:
	if _session == null:
		return
	if _session.has_signal("session_established") \
			and not _session.is_connected("session_established", _on_session_established):
		_session.connect("session_established", _on_session_established)


func _unbind_session() -> void:
	if _session == null:
		return
	if _session.has_signal("session_established") \
			and _session.is_connected("session_established", _on_session_established):
		_session.disconnect("session_established", _on_session_established)


func _on_session_established(_session_data: Dictionary) -> void:
	# 新会话的 Backend 不知道本进程状态，下一帧强制全量上报。
	_last_reported.clear()
	_last_request_id = ""
	_elapsed = _min_interval


func _normalize(raw: Dictionary) -> Dictionary:
	var state := {
		"editor_status": "UNKNOWN",
		"project_status": "MISSING",
		"active_scene": null,
		"current_selection": [],
		"unsaved_resources": [],
		"run_status": "STOPPED",
		"import_status": "IDLE",
	}
	for name in ["editor_status", "project_status", "run_status", "import_status"]:
		var allowed: Array = _allowed_values(name)
		var value: Variant = raw.get(name)
		if typeof(value) == TYPE_STRING and allowed.has(str(value)):
			state[name] = str(value)
	var scene: Variant = raw.get("active_scene")
	if typeof(scene) == TYPE_STRING and _is_resource_path(str(scene)):
		state["active_scene"] = str(scene)
	state["current_selection"] = _normalize_selection(raw.get("current_selection"))
	state["unsaved_resources"] = _normalize_unsaved(raw.get("unsaved_resources"))
	return state


func _allowed_values(name: String) -> Array:
	match name:
		"editor_status":
			return Validator.EDITOR_STATUSES
		"project_status":
			return Validator.PROJECT_STATUSES
		"run_status":
			return Validator.RUN_STATUSES
		"import_status":
			return Validator.IMPORT_STATUSES
	return []


func _normalize_selection(value: Variant) -> Array:
	var result: Array = []
	if typeof(value) != TYPE_ARRAY:
		return result
	for item in value:
		if typeof(item) != TYPE_STRING:
			continue
		var path := str(item)
		if path.is_empty() or path.length() > MAX_SELECTION_PATH:
			continue
		result.append(path)
		if result.size() >= MAX_SELECTION:
			break
	return result


func _normalize_unsaved(value: Variant) -> Array:
	var result: Array = []
	if typeof(value) != TYPE_ARRAY:
		return result
	for item in value:
		if typeof(item) != TYPE_DICTIONARY:
			continue
		var entry: Dictionary = item
		var path := str(entry.get("path", ""))
		var resource_type := str(entry.get("resource_type", ""))
		if not _is_resource_path(path):
			continue
		if resource_type.is_empty() or resource_type.length() > 64:
			continue
		result.append({"path": path, "resource_type": resource_type})
		if result.size() >= MAX_UNSAVED:
			break
	return result


func _is_resource_path(path: String) -> bool:
	if path.is_empty() or path.length() > MAX_RESOURCE_PATH:
		return false
	return path.begins_with("res://") or path.begins_with("user://")


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
	return path if _is_resource_path(path) else null


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
		if path.is_empty() or path.length() > MAX_SELECTION_PATH:
			continue
		result.append(path)
		if result.size() >= MAX_SELECTION:
			break
	return result


## 未保存场景摘要；Godot 未提供查询接口时返回空数组（安全回退）。
func _unsaved_resources() -> Array:
	var iface := _editor_interface()
	if iface == null or not iface.has_method("get_unsaved_scenes"):
		return []
	var value: Variant = iface.call("get_unsaved_scenes")
	var result: Array = []
	if typeof(value) != TYPE_PACKED_STRING_ARRAY and typeof(value) != TYPE_ARRAY:
		return result
	for item in value:
		var path := str(item)
		if not _is_resource_path(path):
			continue
		result.append({"path": path, "resource_type": "scene"})
		if result.size() >= MAX_UNSAVED:
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


func _import_status() -> String:
	var override := str(context.get_config("import_status_override", ""))
	if not override.is_empty():
		return override
	var iface := _editor_interface()
	if iface == null or not iface.has_method("get_resource_filesystem"):
		return "IDLE"
	var filesystem: Variant = iface.call("get_resource_filesystem")
	if filesystem == null or not filesystem.has_method("is_scanning"):
		return "IDLE"
	return "IMPORTING" if bool(filesystem.call("is_scanning")) else "IDLE"
