@tool
extends RefCounted
## 插件统一日志入口（E0-T08 / E3 扩展）。
##
## 输出单行 JSON，字段与 Backend 对齐：
## timestamp / level / component / event / request_id / correlation_id /
## session_id / project_id / error_code / message。
##
## 插件内禁止直接 print / printerr，必须经由此处，便于统一采集与脱敏。
## E3 起只输出白名单字段：ID 类字段截断，凭证类字段脱敏，payload 不落日志。


const PREFIX := "[GodotAI]"
const COMPONENT := "godot_plugin"
const RESERVED := ["timestamp", "level", "component", "event", "message"]

## 允许写入日志的扩展字段白名单，未登记的字段直接丢弃。
const ALLOWED_FIELDS := [
	"request_id", "correlation_id", "session_id", "project_id",
	"editor_instance_id", "message_type", "action", "duration_ms",
	"error_code", "detail", "reason", "status", "version", "required",
	"plugin_version", "godot_version", "service", "dependent", "dependency",
	"order", "count",
]

## 只保留前 8 位，便于关联日志又不泄漏完整标识。
const TRUNCATED_FIELDS := [
	"request_id", "correlation_id", "session_id", "event_id",
	"lease_id", "challenge_id", "snapshot_id",
]

## 键名命中任一片段即视为凭证，只输出 [REDACTED]。
const SENSITIVE_KEY_PARTS := ["token", "secret", "proof", "password", "authorization"]

const MAX_FIELD_LENGTH := 256
const REDACTED := "[REDACTED]"
const OMITTED := "[omitted]"


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
		var field_name := str(key)
		var value := _sanitize_field(field_name, fields[key])
		if value != null:
			payload[field_name] = value

	var line := "%s %s" % [PREFIX, JSON.stringify(payload)]
	match level:
		"ERROR":
			push_error(line)
		"WARNING":
			push_warning(line)
		_:
			print(line)


## 返回 null 表示该字段不进入日志。
static func _sanitize_field(name: String, value: Variant) -> Variant:
	var lowered := name.to_lower()
	if lowered == "payload":
		return null
	for part in SENSITIVE_KEY_PARTS:
		if lowered.contains(part):
			return REDACTED
	if not ALLOWED_FIELDS.has(name):
		return null

	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT:
			return value
		TYPE_STRING, TYPE_STRING_NAME:
			var text := str(value)
			if TRUNCATED_FIELDS.has(name) and text.length() > 8:
				return text.substr(0, 8)
			if text.length() > MAX_FIELD_LENGTH:
				return text.substr(0, MAX_FIELD_LENGTH)
			return text
		_:
			return OMITTED
