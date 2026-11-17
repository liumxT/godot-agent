@tool
extends RefCounted
## Shared Contracts 1.0 校验器（插件侧）。
##
## 只做结构校验，不包含任何业务判断，也不允许引入网络或编辑器依赖。
## 字段规则必须与 packages/contracts 下的 JSON Schema 保持一致。


const PROTOCOL_VERSION := "1.0"

const ID_PATTERN := "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
const ACTION_PATTERN := "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$"
const ERROR_CODE_PATTERN := "^[A-Z][A-Z0-9_]{2,63}$"
const TIMESTAMP_PATTERN := "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d{1,6})?Z$"
const SOURCES := ["backend", "plugin"]

const REQUEST_FIELDS := [
	"protocol_version", "request_id", "correlation_id", "timestamp",
	"session_id", "project_id", "action", "payload",
]
const RESPONSE_FIELDS := ["protocol_version", "request_id", "success", "data", "error"]
const EVENT_FIELDS := [
	"protocol_version", "event_id", "event_type", "timestamp", "source",
	"session_id", "project_id", "correlation_id", "payload",
]
const ERROR_FIELDS := ["code", "message", "details", "retryable", "correlation_id"]

static var _regex_cache: Dictionary = {}


static func validate_request(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("request must be an object")
		return errors
	var d: Dictionary = data
	_check_protocol_version(d, errors)
	_check_required_id(d, "request_id", errors)
	for name in ["correlation_id", "session_id", "project_id"]:
		_check_optional_id(d, name, errors)
	_check_timestamp(d, errors)
	_check_action(d, errors)
	_check_object(d, "payload", errors)
	_check_unknown(d, REQUEST_FIELDS, errors)
	return errors


static func validate_response(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("response must be an object")
		return errors
	var d: Dictionary = data
	_check_protocol_version(d, errors)
	_check_required_id(d, "request_id", errors)

	if not d.has("success") or typeof(d["success"]) != TYPE_BOOL:
		errors.append("success must be a boolean")

	if not d.has("data"):
		errors.append("missing required field: data")
	elif typeof(d["data"]) != TYPE_DICTIONARY and typeof(d["data"]) != TYPE_NIL:
		errors.append("data must be an object or null")

	if not d.has("error"):
		errors.append("missing required field: error")
		_check_unknown(d, RESPONSE_FIELDS, errors)
		return errors

	var error_value: Variant = d["error"]
	if typeof(error_value) == TYPE_NIL:
		if bool(d.get("success", false)):
			pass
	elif typeof(error_value) == TYPE_DICTIONARY:
		errors.append_array(validate_error(error_value))
		if bool(d.get("success", false)):
			errors.append("error must be null when success is true")
	else:
		errors.append("error must be an object or null")

	if not bool(d.get("success", true)) and typeof(error_value) == TYPE_NIL:
		errors.append("error is required when success is false")

	_check_unknown(d, RESPONSE_FIELDS, errors)
	return errors


static func validate_event(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("event must be an object")
		return errors
	var d: Dictionary = data
	_check_protocol_version(d, errors)
	_check_required_id(d, "event_id", errors)
	for name in ["session_id", "project_id", "correlation_id"]:
		_check_optional_id(d, name, errors)
	_check_timestamp(d, errors)

	if not d.has("event_type"):
		errors.append("missing required field: event_type")
	elif typeof(d["event_type"]) != TYPE_STRING or not _matches(str(d["event_type"]), ACTION_PATTERN):
		errors.append("event_type has invalid format")

	if not d.has("source") or not SOURCES.has(str(d.get("source", ""))):
		errors.append("source must be one of: %s" % ", ".join(SOURCES))

	_check_object(d, "payload", errors)
	_check_unknown(d, EVENT_FIELDS, errors)
	return errors


static func validate_error(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("error must be an object")
		return errors
	var d: Dictionary = data

	if not d.has("code"):
		errors.append("missing required field: code")
	elif typeof(d["code"]) != TYPE_STRING or not _matches(str(d["code"]), ERROR_CODE_PATTERN):
		errors.append("code must be upper case with underscores")

	if not d.has("message"):
		errors.append("missing required field: message")
	elif typeof(d["message"]) != TYPE_STRING or str(d["message"]).is_empty():
		errors.append("message must be a non-empty string")
	elif str(d["message"]).length() > 1024:
		errors.append("message is too long")

	_check_object(d, "details", errors)

	if not d.has("retryable") or typeof(d["retryable"]) != TYPE_BOOL:
		errors.append("retryable must be a boolean")

	_check_required_id(d, "correlation_id", errors)
	_check_unknown(d, ERROR_FIELDS, errors)
	return errors


static func _check_protocol_version(d: Dictionary, errors: Array) -> void:
	if not d.has("protocol_version"):
		errors.append("missing required field: protocol_version")
		return
	var value: Variant = d["protocol_version"]
	if typeof(value) != TYPE_STRING or not _matches(str(value), "^1\\.[0-9]+$"):
		errors.append("protocol_version must match 1.x")


static func _check_timestamp(d: Dictionary, errors: Array) -> void:
	if not d.has("timestamp"):
		errors.append("missing required field: timestamp")
		return
	var value: Variant = d["timestamp"]
	if typeof(value) != TYPE_STRING or not _matches(str(value), TIMESTAMP_PATTERN):
		errors.append("timestamp must be UTC RFC3339 like 2026-11-17T10:00:00Z")


static func _check_action(d: Dictionary, errors: Array) -> void:
	if not d.has("action"):
		errors.append("missing required field: action")
		return
	var value: Variant = d["action"]
	if typeof(value) != TYPE_STRING or not _matches(str(value), ACTION_PATTERN):
		errors.append("action must be lower-case dotted, e.g. project.scan")


static func _check_object(d: Dictionary, name: String, errors: Array) -> void:
	if not d.has(name):
		errors.append("missing required field: %s" % name)
	elif typeof(d[name]) != TYPE_DICTIONARY:
		errors.append("%s must be an object" % name)


static func _check_required_id(d: Dictionary, name: String, errors: Array) -> void:
	if not d.has(name):
		errors.append("missing required field: %s" % name)
		return
	_check_id_value(name, d[name], errors)


static func _check_optional_id(d: Dictionary, name: String, errors: Array) -> void:
	if d.has(name):
		_check_id_value(name, d[name], errors)


static func _check_id_value(name: String, value: Variant, errors: Array) -> void:
	if typeof(value) != TYPE_STRING:
		errors.append("%s must be a string" % name)
	elif not _matches(str(value), ID_PATTERN):
		errors.append("%s has invalid format" % name)


static func _check_unknown(d: Dictionary, allowed: Array, errors: Array) -> void:
	for key in d.keys():
		if not allowed.has(String(key)):
			errors.append("unknown field: %s" % key)


static func _matches(value: String, pattern: String) -> bool:
	if not _regex_cache.has(pattern):
		_regex_cache[pattern] = RegEx.create_from_string(pattern)
	return _regex_cache[pattern].search(value) != null
