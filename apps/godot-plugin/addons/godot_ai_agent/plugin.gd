@tool
extends EditorPlugin
## Godot AI Agent 插件入口（E3-M1）。
##
## 只做生命周期转发：启用/关闭/逐帧调度均委托给 core/plugin_lifecycle.gd。
## 连接、会话、心跳等通信细节由后续服务实现，本文件不得直接引用。
## 另外提供「运行时探针」开关：只有用户显式启用后才注入 autoload，
## 不静默修改 project.godot。

const PLUGIN_VERSION := "0.1.0"

const PluginLog := preload("res://addons/godot_ai_agent/core/logger.gd")
const PluginLifecycle := preload("res://addons/godot_ai_agent/core/plugin_lifecycle.gd")

const RUNTIME_AUTOLOAD_NAME := "GodotAIRuntimeBridge"
const RUNTIME_SCRIPT_PATH := "res://addons/godot_ai_agent/runtime/runtime_bridge.gd"
const RUNTIME_MENU_ENABLE := "启用运行时探针"
const RUNTIME_MENU_DISABLE := "禁用运行时探针"


var _lifecycle: Object = null
var _enabled := false


func _enter_tree() -> void:
	# 重复启用保护：避免服务与 Dock 被重复注册
	if _enabled:
		PluginLog.warn("plugin_already_enabled")
		return

	_enabled = true
	_lifecycle = PluginLifecycle.new()
	_lifecycle.call("enable", self, DOCK_SLOT_RIGHT_UL, PLUGIN_VERSION, true)
	add_tool_menu_item(RUNTIME_MENU_ENABLE, _enable_runtime_probe)
	add_tool_menu_item(RUNTIME_MENU_DISABLE, _disable_runtime_probe)
	set_process(true)


func _exit_tree() -> void:
	if not _enabled:
		return

	set_process(false)
	remove_tool_menu_item(RUNTIME_MENU_ENABLE)
	remove_tool_menu_item(RUNTIME_MENU_DISABLE)
	if _lifecycle != null:
		_lifecycle.call("disable", "editor_plugin_disabled")
	_lifecycle = null
	_enabled = false


func _process(delta: float) -> void:
	if _lifecycle != null:
		_lifecycle.call("tick", delta)


func _enable_runtime_probe() -> void:
	if ProjectSettings.has_setting("autoload/%s" % RUNTIME_AUTOLOAD_NAME):
		PluginLog.info("runtime_probe_already_enabled")
		return
	add_autoload_singleton(RUNTIME_AUTOLOAD_NAME, RUNTIME_SCRIPT_PATH)
	PluginLog.info("runtime_probe_enabled")


func _disable_runtime_probe() -> void:
	if not ProjectSettings.has_setting("autoload/%s" % RUNTIME_AUTOLOAD_NAME):
		PluginLog.info("runtime_probe_not_enabled")
		return
	remove_autoload_singleton(RUNTIME_AUTOLOAD_NAME)
	PluginLog.info("runtime_probe_disabled")
