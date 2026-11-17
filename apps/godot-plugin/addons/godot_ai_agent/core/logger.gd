@tool
extends RefCounted
## 插件统一日志入口（E0-T08）。
##
## 输出单行 JSON，字段与 Backend 对齐：
## timestamp / level / component / event / request_id / correlation_id /
## session_id / project_id / error_code / message。
##
## 插件内禁止直接 print / printerr，必须经由此处，便于统一采集与脱敏。

const PREFIX := "[GodotAI]"
const COMPONENT := "godot_plugin"
const RESERVED := ["timestamp", "level", "component", "event", "message"]


static func info(event: String, fields: Dictionary = {}) -> void:
	_emit("INFO", event, fields)


static func warn(event: String, fields: Dictionary = {}) -> void:
	_emit("WARNING", event, fields)


static func error(event: String, fields: Dictionary = {}) -> void:
	_emit("ERROR", event, fields)


static func _emit(level: String, event: String, fields: Dictionary) -> void:
	var payload := {
		"timestamp": Time.get_datetime_string_from_system(true),
		"level": level,
		"component": COMPONENT,
		"event": event,
		"message": str(fields.get("message", event)),
	}
	for key in fields:
		if RESERVED.has(key):
			continue
		payload[key] = fields[key]

	var line := "%s %s" % [PREFIX, JSON.stringify(payload)]
	match level:
		"ERROR":
			push_error(line)
		"WARNING":
			push_warning(line)
		_:
			print(line)
