@tool
extends RefCounted
## 插件统一日志入口。
##
## 插件内所有日志必须经由此处，禁止直接 print，便于后续接入统一前缀与上报。


const PREFIX := "[GodotAI]"


static func info(message: String) -> void:
	print("%s %s" % [PREFIX, message])


static func warn(message: String) -> void:
	push_warning("%s %s" % [PREFIX, message])


static func error(message: String) -> void:
	push_error("%s %s" % [PREFIX, message])
