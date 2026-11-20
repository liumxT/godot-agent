@tool
extends RefCounted
## 插件上下文（E3-T01）。
##
## 持有配置、宿主 EditorPlugin、EditorInterface 与单调时钟，并统一转发日志。
## 服务只通过本对象获取共享能力，禁止互相持有具体实例。
## 插件关闭时必须调用 release()，确保不残留 Editor 对象引用。


const PluginLog := preload("res://addons/godot_ai_agent/core/logger.gd")

## 仅包含 E3 阶段必需的默认值；地址来源优先级由 Discovery 服务负责。
const DEFAULT_CONFIG := {
	"backend_url": "http://127.0.0.1:8765",
	"auto_connect": true,
}


var _config: Dictionary = {}
var _host: Object = null
var _editor_interface: Object = null
var _plugin_version := ""
var _godot_version := ""
var _created_at_ms := 0
var _released := false


func _init(host: Object = null, plugin_version: String = "", godot_version: String = "") -> void:
	_host = host
	_plugin_version = plugin_version
	_godot_version = godot_version
	_created_at_ms = Time.get_ticks_msec()
	_config = DEFAULT_CONFIG.duplicate(true)
	if _host != null and _host.has_method("get_editor_interface"):
		_editor_interface = _host.call("get_editor_interface")


func get_config(key: String, default_value: Variant = null) -> Variant:
	if _config.has(key):
		return _config[key]
	return default_value


func set_config(key: String, value: Variant) -> void:
	_config[key] = value


func get_host() -> Object:
	return _host


func get_editor_interface() -> Object:
	return _editor_interface


func plugin_version() -> String:
	return _plugin_version


func godot_version() -> String:
	return _godot_version


func is_released() -> bool:
	return _released


## 单调时钟（毫秒），用于心跳、超时与退避计算。
func now_ms() -> int:
	return Time.get_ticks_msec()


func elapsed_ms(since_ms: int) -> int:
	return maxi(0, now_ms() - since_ms)


func uptime_ms() -> int:
	return elapsed_ms(_created_at_ms)


func log_info(event: String, fields: Dictionary = {}) -> void:
	PluginLog.info(event, fields)


func log_warn(event: String, fields: Dictionary = {}) -> void:
	PluginLog.warn(event, fields)


func log_error(event: String, fields: Dictionary = {}) -> void:
	PluginLog.error(event, fields)


## 清理 Editor 对象引用；之后上下文不可再用于编辑器操作。
func release() -> void:
	_host = null
	_editor_interface = null
	_released = true
