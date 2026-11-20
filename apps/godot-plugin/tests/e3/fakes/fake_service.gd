@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## 测试用服务：记录生命周期调用，并可按需制造失败。


var calls: Array = []
var trace: Array = []
var fail_initialize := false
var fail_start := false


func _initialize() -> bool:
	_record("initialize")
	return not fail_initialize


func _start() -> bool:
	_record("start")
	return not fail_start


func _tick(_delta: float) -> void:
	_record("tick")


func _stop(reason: String) -> void:
	_record("stop:%s" % reason)


func _dispose() -> void:
	_record("dispose")


func _record(entry: String) -> void:
	calls.append(entry)
	trace.append("%s:%s" % [service_name, entry])
