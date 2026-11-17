@tool
extends EditorPlugin
## Godot AI Agent 插件入口（E0 骨架）。
##
## 本阶段只负责：版本校验、状态面板的注册与释放、最小日志。
## Editor Bridge / Session / Heartbeat 在 E3 实现，此处不得提前引入。


const PLUGIN_VERSION := "0.1.0"
const MIN_GODOT_MAJOR := 4
const MIN_GODOT_MINOR := 5

const PluginLog := preload("res://addons/godot_ai_agent/core/logger.gd")
const StatusPanel := preload("res://addons/godot_ai_agent/ui/status_panel.gd")


var _panel: Control = null
var _enabled := false


func _enter_tree() -> void:
	# 重复启用保护：避免面板被重复注册
	if _enabled:
		PluginLog.warn("plugin_already_enabled")
		return

	var version := Engine.get_version_info()
	var version_text: String = str(version.get("string", "unknown"))

	if not _is_supported(version):
		PluginLog.error("unsupported_godot_version", {
			"error_code": "UNSUPPORTED_GODOT_VERSION",
			"version": version_text,
			"required": "%d.%d+" % [MIN_GODOT_MAJOR, MIN_GODOT_MINOR],
		})
		_create_panel(version_text, false)
		_enabled = true
		return

	_create_panel(version_text, true)
	_enabled = true
	PluginLog.info("plugin_enabled", {"version": PLUGIN_VERSION})


func _exit_tree() -> void:
	if not _enabled:
		return

	if is_instance_valid(_panel):
		remove_control_from_docks(_panel)
		_panel.queue_free()
	_panel = null
	_enabled = false
	PluginLog.info("plugin_disabled")


func _create_panel(version_text: String, supported: bool) -> void:
	_panel = StatusPanel.new()
	_panel.set_godot_version(version_text)
	_panel.set_backend_status("未连接")
	if supported:
		_panel.set_plugin_status("已启用 v%s" % PLUGIN_VERSION)
	else:
		_panel.set_plugin_status("版本不支持（需 %d.%d+）" % [MIN_GODOT_MAJOR, MIN_GODOT_MINOR])
	add_control_to_dock(DOCK_SLOT_RIGHT_UL, _panel)


func _is_supported(version: Dictionary) -> bool:
	var major := int(version.get("major", 0))
	var minor := int(version.get("minor", 0))
	if major != MIN_GODOT_MAJOR:
		return false
	return minor >= MIN_GODOT_MINOR
