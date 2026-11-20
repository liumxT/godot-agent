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

const API_VERSION := "v1"
const ENVIRONMENTS := ["development", "test", "production"]
const LIFECYCLE_STATES := [
	"CREATED", "INITIALIZING", "STARTING", "RUNNING", "STOPPING", "STOPPED", "FAILED",
]
const DATABASE_STATUSES := ["ready", "unavailable"]
const APP_VERSION_PATTERN := "^\\d+\\.\\d+\\.\\d+([.-][A-Za-z0-9]+)*$"
const PROTOCOL_VERSION_PATTERN := "^\\d+\\.\\d+$"
const STARTED_AT_PATTERN := "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d{1,6})?(Z|[+-]\\d{2}:\\d{2})$"

const SYSTEM_INFO_FIELDS := [
	"app_name", "app_version", "api_version", "protocol_version", "environment",
]
const SYSTEM_STATUS_FIELDS := ["state", "started_at", "uptime_seconds", "database_status"]

const CLIENT_ID_PATTERN := "^cli_[a-z0-9]{12}$"
const CHALLENGE_ID_PATTERN := "^chl_[a-z0-9]{12}$"
const SECRET_PATTERN := "^[A-Za-z0-9_-]{43}$"
const ACCESS_TOKEN_PATTERN := "^gda_[A-Za-z0-9_-]{43}$"
const CLIENT_TYPES := ["godot_editor", "admin", "tool"]
const CLIENT_FIELDS := [
	"client_id", "client_secret", "client_type", "client_name", "status", "created_at",
]
const AUTH_CHALLENGE_FIELDS := ["challenge_id", "challenge", "expires_at"]
const AUTH_TOKEN_FIELDS := ["access_token", "token_type", "expires_at"]

const SESSION_ID_PATTERN := "^ses_[a-z0-9]{12}$"
const SESSION_TOKEN_PATTERN := "^gds_[A-Za-z0-9_-]{43}$"
const ACCESS_ID_PATTERN := "^acc_[a-z0-9]{12}$"
const PROJECT_ID_PATTERN := "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
const SESSION_STATUSES := ["ACTIVE", "EXPIRED", "REVOKED", "CLOSED"]
const ACCESS_LEVELS := ["owner", "editor", "viewer"]
const ACCESS_STATUSES := ["ACTIVE", "REVOKED", "EXPIRED"]
const SESSION_FIELDS := [
	"session_id", "client_id", "status", "created_at", "last_seen_at",
	"expires_at", "revoked_at", "closed_at",
]
const SESSION_ISSUED_FIELDS := ["session_token", "token_type", "expires_at", "session"]
const PROJECT_ACCESS_FIELDS := [
	"access_id", "project_id", "client_id", "session_id", "access_level",
	"status", "granted_by", "granted_at", "expires_at",
]

const CONTROL_ID_PATTERN := "^ctl_[a-z0-9]{8}$"
const LEASE_ID_PATTERN := "^lea_[a-z0-9]{12}$"
const SNAPSHOT_ID_PATTERN := "^snp_[a-z0-9]{12}$"
const RUNTIME_ID_PATTERN := "^rti_[a-z0-9]{12}$"
const EDITOR_INSTANCE_PATTERN := "^edi_[a-z0-9]{12}$"
const PROJECT_FINGERPRINT_PATTERN := "^[A-Za-z0-9_-]{16,64}$"
const RESOURCE_PATH_PATTERN := "^(res|user)://.+$"
const PROJECT_ROOT_PATTERN := "^(res|user)://.*$"

const CONTROL_MESSAGE_TYPES := [
	"HELLO", "AUTH_CHALLENGE", "AUTH_RESPONSE", "SESSION_CREATED", "RUNTIME_REGISTERED", "ERROR",
]
const LEASE_STATUSES := ["ACTIVE", "RENEWING", "EXPIRED", "REVOKED"]
const BINDING_STATUSES := ["CONNECTED", "DISCONNECTED", "RECOVERING", "CLOSED"]
const EDITOR_STATUSES := ["READY", "BUSY", "IMPORTING", "UNKNOWN"]
const PROJECT_STATUSES := ["READY", "LOADING", "MISSING"]
const RUN_STATUSES := ["STOPPED", "RUNNING", "PAUSED"]
const IMPORT_STATUSES := ["IDLE", "IMPORTING", "FAILED"]
const BUILD_MODES := ["debug", "release"]
const RUNTIME_STATUSES := ["RUNNING", "STOPPED", "CRASHED"]

const CONTROL_FIELDS := [
	"protocol_version", "message_id", "message_type", "timestamp",
	"session_id", "project_id", "correlation_id", "payload",
]
const LEASE_FIELDS := [
	"lease_id", "session_id", "project_id", "fencing_token", "status",
	"issued_at", "renewed_at", "expires_at", "revoked_at",
]
const SESSION_CREATED_FIELDS := [
	"session_id", "session_token", "token_type", "expires_at",
	"editor_instance_id", "project_id", "lease",
	"heartbeat_interval_seconds", "request_timeout_seconds",
]
const BINDING_FIELDS := [
	"session_id", "editor_instance_id", "project_id", "godot_version",
	"plugin_version", "transport", "binding_status", "connected_at",
	"disconnected_at", "last_seen_at", "closed_at",
]
const EDITOR_STATE_FIELDS := [
	"editor_status", "project_status", "active_scene", "current_selection",
	"unsaved_resources", "run_status", "import_status",
]
const SNAPSHOT_FIELDS := [
	"snapshot_id", "session_id", "project_id", "editor_instance_id",
	"snapshot_version", "last_event_sequence", "created_at",
	"editor_status", "project_status", "active_scene", "current_selection",
	"unsaved_resources", "run_status", "import_status", "truncated",
]
const RUNTIME_FIELDS := [
	"runtime_instance_id", "project_root", "project_fingerprint", "process_id",
	"started_at", "godot_version", "build_mode", "status",
]
const UNSAVED_RESOURCE_FIELDS := ["path", "resource_type"]

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


static func validate_system(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("system response must be an object")
		return errors
	var d: Dictionary = data
	if d.has("app_name") or d.has("api_version"):
		_validate_system_info(d, errors)
	else:
		_validate_system_status(d, errors)
	return errors


static func _validate_system_info(d: Dictionary, errors: Array) -> void:
	for name in SYSTEM_INFO_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)

	if d.has("app_name"):
		var app_name: Variant = d["app_name"]
		if typeof(app_name) != TYPE_STRING or str(app_name).is_empty():
			errors.append("app_name must be a non-empty string")
		elif str(app_name).length() > 64:
			errors.append("app_name is too long")

	if d.has("app_version"):
		var app_version: Variant = d["app_version"]
		if typeof(app_version) != TYPE_STRING \
				or not _matches(str(app_version), APP_VERSION_PATTERN):
			errors.append("app_version has invalid format")

	if d.has("api_version") and str(d["api_version"]) != API_VERSION:
		errors.append("api_version must be %s" % API_VERSION)

	if d.has("protocol_version"):
		var protocol_version: Variant = d["protocol_version"]
		if typeof(protocol_version) != TYPE_STRING \
				or not _matches(str(protocol_version), PROTOCOL_VERSION_PATTERN):
			errors.append("protocol_version has invalid format")

	if d.has("environment") and not ENVIRONMENTS.has(str(d["environment"])):
		errors.append("environment must be one of: %s" % ", ".join(ENVIRONMENTS))

	_check_unknown(d, SYSTEM_INFO_FIELDS, errors)


static func _validate_system_status(d: Dictionary, errors: Array) -> void:
	for name in SYSTEM_STATUS_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)

	if d.has("state") and not LIFECYCLE_STATES.has(str(d["state"])):
		errors.append("state is not a known lifecycle state")

	if d.has("started_at"):
		var started_at: Variant = d["started_at"]
		if typeof(started_at) != TYPE_NIL:
			if typeof(started_at) != TYPE_STRING \
					or not _matches(str(started_at), STARTED_AT_PATTERN):
				errors.append("started_at must be an RFC3339 timestamp or null")

	if d.has("uptime_seconds"):
		var uptime: Variant = d["uptime_seconds"]
		if typeof(uptime) != TYPE_NIL:
			if typeof(uptime) != TYPE_INT and typeof(uptime) != TYPE_FLOAT:
				errors.append("uptime_seconds must be a number or null")
			elif float(uptime) < 0.0:
				errors.append("uptime_seconds must not be negative")

	if d.has("database_status") and not DATABASE_STATUSES.has(str(d["database_status"])):
		errors.append("database_status must be one of: %s" % ", ".join(DATABASE_STATUSES))

	_check_unknown(d, SYSTEM_STATUS_FIELDS, errors)


static func validate_client(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("client response must be an object")
		return errors
	var d: Dictionary = data

	for name in CLIENT_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)

	if d.has("client_id"):
		_check_pattern_field(d, "client_id", CLIENT_ID_PATTERN, errors)
	if d.has("client_secret"):
		_check_pattern_field(d, "client_secret", SECRET_PATTERN, errors)
	if d.has("client_type") and not CLIENT_TYPES.has(str(d["client_type"])):
		errors.append("client_type must be one of: %s" % ", ".join(CLIENT_TYPES))
	if d.has("client_name"):
		var client_name: Variant = d["client_name"]
		if typeof(client_name) != TYPE_STRING or str(client_name).is_empty():
			errors.append("client_name must be a non-empty string")
		elif str(client_name).length() > 128:
			errors.append("client_name is too long")
	if d.has("status") and str(d["status"]) != "active":
		errors.append("status must be active")
	_check_timestamp_field(d, "created_at", errors)
	_check_unknown(d, CLIENT_FIELDS, errors)
	return errors


static func validate_auth(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("auth response must be an object")
		return errors
	var d: Dictionary = data

	if d.has("challenge_id"):
		for name in AUTH_CHALLENGE_FIELDS:
			if not d.has(name):
				errors.append("missing required field: %s" % name)
		_check_pattern_field(d, "challenge_id", CHALLENGE_ID_PATTERN, errors)
		_check_pattern_field(d, "challenge", SECRET_PATTERN, errors)
		_check_timestamp_field(d, "expires_at", errors)
		_check_unknown(d, AUTH_CHALLENGE_FIELDS, errors)
		return errors

	for name in AUTH_TOKEN_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)
	_check_pattern_field(d, "access_token", ACCESS_TOKEN_PATTERN, errors)
	if d.has("token_type") and str(d["token_type"]) != "Bearer":
		errors.append("token_type must be Bearer")
	_check_timestamp_field(d, "expires_at", errors)
	_check_unknown(d, AUTH_TOKEN_FIELDS, errors)
	return errors


static func validate_session(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("session response must be an object")
		return errors
	var d: Dictionary = data

	if d.has("session_token"):
		for name in SESSION_ISSUED_FIELDS:
			if not d.has(name):
				errors.append("missing required field: %s" % name)
		_check_pattern_field(d, "session_token", SESSION_TOKEN_PATTERN, errors)
		if d.has("token_type") and str(d["token_type"]) != "Bearer":
			errors.append("token_type must be Bearer")
		_check_timestamp_field(d, "expires_at", errors)
		if d.has("session"):
			if typeof(d["session"]) != TYPE_DICTIONARY:
				errors.append("session must be an object")
			else:
				errors.append_array(_validate_session_fields(d["session"]))
		_check_unknown(d, SESSION_ISSUED_FIELDS, errors)
		return errors

	errors.append_array(_validate_session_fields(d))
	return errors


static func _validate_session_fields(d: Dictionary) -> Array:
	var errors: Array = []
	for name in SESSION_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)

	_check_pattern_field(d, "session_id", SESSION_ID_PATTERN, errors)
	_check_pattern_field(d, "client_id", CLIENT_ID_PATTERN, errors)
	if d.has("status") and not SESSION_STATUSES.has(str(d["status"])):
		errors.append("status is not a known session status")
	_check_timestamp_field(d, "created_at", errors)
	_check_timestamp_field(d, "expires_at", errors)
	for name in ["last_seen_at", "revoked_at", "closed_at"]:
		_check_nullable_timestamp_field(d, name, errors)
	_check_unknown(d, SESSION_FIELDS, errors)
	return errors


static func validate_project_access(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("project access response must be an object")
		return errors
	var d: Dictionary = data

	for name in PROJECT_ACCESS_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)

	_check_pattern_field(d, "access_id", ACCESS_ID_PATTERN, errors)
	_check_pattern_field(d, "project_id", PROJECT_ID_PATTERN, errors)
	_check_pattern_field(d, "client_id", CLIENT_ID_PATTERN, errors)
	_check_pattern_field(d, "session_id", SESSION_ID_PATTERN, errors)
	_check_pattern_field(d, "granted_by", CLIENT_ID_PATTERN, errors)
	if d.has("access_level") and not ACCESS_LEVELS.has(str(d["access_level"])):
		errors.append("access_level must be one of: %s" % ", ".join(ACCESS_LEVELS))
	if d.has("status") and not ACCESS_STATUSES.has(str(d["status"])):
		errors.append("status must be one of: %s" % ", ".join(ACCESS_STATUSES))
	_check_timestamp_field(d, "granted_at", errors)
	_check_timestamp_field(d, "expires_at", errors)
	_check_unknown(d, PROJECT_ACCESS_FIELDS, errors)
	return errors


static func validate_bridge_control(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("control frame must be an object")
		return errors
	var d: Dictionary = data
	for name in CONTROL_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)
	_check_protocol_version(d, errors)
	_check_pattern_field(d, "message_id", CONTROL_ID_PATTERN, errors)
	if not d.has("message_type") or not CONTROL_MESSAGE_TYPES.has(str(d["message_type"])):
		errors.append("message_type is not a known control type")
	_check_timestamp(d, errors)
	_check_pattern_or_null(d, "session_id", SESSION_ID_PATTERN, errors)
	_check_pattern_or_null(d, "project_id", PROJECT_ID_PATTERN, errors)
	_check_pattern_or_null(d, "correlation_id", ID_PATTERN, errors)
	_check_object(d, "payload", errors)
	_check_unknown(d, CONTROL_FIELDS, errors)
	return errors


static func validate_bridge_lease(data: Variant) -> Array:
	return _validate_lease_fields(data)


static func validate_bridge_session_created(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("session created payload must be an object")
		return errors
	var d: Dictionary = data
	for name in SESSION_CREATED_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)
	_check_pattern_field(d, "session_id", SESSION_ID_PATTERN, errors)
	_check_pattern_field(d, "session_token", SESSION_TOKEN_PATTERN, errors)
	if d.has("token_type") and str(d["token_type"]) != "Bearer":
		errors.append("token_type must be Bearer")
	_check_timestamp_field(d, "expires_at", errors)
	_check_pattern_field(d, "editor_instance_id", EDITOR_INSTANCE_PATTERN, errors)
	_check_pattern_field(d, "project_id", PROJECT_ID_PATTERN, errors)
	if d.has("lease"):
		errors.append_array(_validate_lease_fields(d["lease"]))
	_check_integer_field(d, "heartbeat_interval_seconds", 1, errors, 300)
	_check_integer_field(d, "request_timeout_seconds", 1, errors, 120)
	_check_unknown(d, SESSION_CREATED_FIELDS, errors)
	return errors


static func validate_bridge_session_binding(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("session binding must be an object")
		return errors
	var d: Dictionary = data
	for name in BINDING_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)
	_check_pattern_field(d, "session_id", SESSION_ID_PATTERN, errors)
	_check_pattern_field(d, "editor_instance_id", EDITOR_INSTANCE_PATTERN, errors)
	_check_pattern_field(d, "project_id", PROJECT_ID_PATTERN, errors)
	_check_pattern_field(d, "godot_version", APP_VERSION_PATTERN, errors)
	_check_pattern_field(d, "plugin_version", APP_VERSION_PATTERN, errors)
	if d.has("transport") and str(d["transport"]) != "websocket":
		errors.append("transport must be websocket")
	if d.has("binding_status") and not BINDING_STATUSES.has(str(d["binding_status"])):
		errors.append("binding_status is not a known status")
	_check_timestamp_field(d, "connected_at", errors)
	for name in ["disconnected_at", "last_seen_at", "closed_at"]:
		_check_nullable_timestamp_field(d, name, errors)
	_check_unknown(d, BINDING_FIELDS, errors)
	return errors


static func validate_bridge_editor_state(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("editor state must be an object")
		return errors
	var d: Dictionary = data
	for name in EDITOR_STATE_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)
	_validate_editor_state_fields(d, errors)
	_check_unknown(d, EDITOR_STATE_FIELDS, errors)
	return errors


static func validate_bridge_snapshot(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("snapshot must be an object")
		return errors
	var d: Dictionary = data
	for name in SNAPSHOT_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)
	_check_pattern_field(d, "snapshot_id", SNAPSHOT_ID_PATTERN, errors)
	_check_pattern_field(d, "session_id", SESSION_ID_PATTERN, errors)
	_check_pattern_field(d, "project_id", PROJECT_ID_PATTERN, errors)
	_check_pattern_field(d, "editor_instance_id", EDITOR_INSTANCE_PATTERN, errors)
	_check_integer_field(d, "snapshot_version", 1, errors)
	_check_integer_field(d, "last_event_sequence", 0, errors)
	_check_timestamp_field(d, "created_at", errors)
	_validate_editor_state_fields(d, errors)
	_check_bool_field(d, "truncated", errors)
	_check_unknown(d, SNAPSHOT_FIELDS, errors)
	return errors


static func validate_bridge_runtime(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("runtime report must be an object")
		return errors
	var d: Dictionary = data
	for name in RUNTIME_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)
	_check_pattern_field(d, "runtime_instance_id", RUNTIME_ID_PATTERN, errors)
	_check_pattern_field(d, "project_root", PROJECT_ROOT_PATTERN, errors)
	_check_pattern_field(d, "project_fingerprint", PROJECT_FINGERPRINT_PATTERN, errors)
	_check_integer_field(d, "process_id", 1, errors)
	_check_timestamp_field(d, "started_at", errors)
	_check_pattern_field(d, "godot_version", APP_VERSION_PATTERN, errors)
	if d.has("build_mode") and not BUILD_MODES.has(str(d["build_mode"])):
		errors.append("build_mode must be debug or release")
	if d.has("status") and not RUNTIME_STATUSES.has(str(d["status"])):
		errors.append("status is not a known runtime status")
	_check_unknown(d, RUNTIME_FIELDS, errors)
	return errors


static func _validate_lease_fields(data: Variant) -> Array:
	var errors: Array = []
	if typeof(data) != TYPE_DICTIONARY:
		errors.append("lease must be an object")
		return errors
	var d: Dictionary = data
	for name in LEASE_FIELDS:
		if not d.has(name):
			errors.append("missing required field: %s" % name)
	_check_pattern_field(d, "lease_id", LEASE_ID_PATTERN, errors)
	_check_pattern_field(d, "session_id", SESSION_ID_PATTERN, errors)
	_check_pattern_field(d, "project_id", PROJECT_ID_PATTERN, errors)
	_check_integer_field(d, "fencing_token", 1, errors)
	if d.has("status") and not LEASE_STATUSES.has(str(d["status"])):
		errors.append("status is not a known lease status")
	_check_timestamp_field(d, "issued_at", errors)
	_check_timestamp_field(d, "expires_at", errors)
	for name in ["renewed_at", "revoked_at"]:
		_check_nullable_timestamp_field(d, name, errors)
	_check_unknown(d, LEASE_FIELDS, errors)
	return errors


static func _validate_editor_state_fields(d: Dictionary, errors: Array) -> void:
	if d.has("editor_status") and not EDITOR_STATUSES.has(str(d["editor_status"])):
		errors.append("editor_status is not a known status")
	if d.has("project_status") and not PROJECT_STATUSES.has(str(d["project_status"])):
		errors.append("project_status is not a known status")
	_check_pattern_or_null(d, "active_scene", RESOURCE_PATH_PATTERN, errors)
	_check_string_array(d, "current_selection", 64, 512, errors)
	_check_unsaved_resources(d, "unsaved_resources", errors)
	if d.has("run_status") and not RUN_STATUSES.has(str(d["run_status"])):
		errors.append("run_status is not a known status")
	if d.has("import_status") and not IMPORT_STATUSES.has(str(d["import_status"])):
		errors.append("import_status is not a known status")


static func _check_pattern_or_null(d: Dictionary, name: String, pattern: String, errors: Array) -> void:
	if not d.has(name) or typeof(d[name]) == TYPE_NIL:
		return
	_check_pattern_field(d, name, pattern, errors)


static func _check_integer_field(
	d: Dictionary, name: String, minimum: int, errors: Array, maximum: int = 0
) -> void:
	if not d.has(name):
		return
	var value: Variant = d[name]
	if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
		errors.append("%s must be an integer" % name)
		return
	var number := float(value)
	if floor(number) != number:
		errors.append("%s must be an integer" % name)
	elif number < float(minimum):
		errors.append("%s must be >= %d" % [name, minimum])
	elif maximum > 0 and number > float(maximum):
		errors.append("%s must be <= %d" % [name, maximum])


static func _check_bool_field(d: Dictionary, name: String, errors: Array) -> void:
	if not d.has(name):
		return
	if typeof(d[name]) != TYPE_BOOL:
		errors.append("%s must be a boolean" % name)


static func _check_string_array(
	d: Dictionary, name: String, max_items: int, max_length: int, errors: Array
) -> void:
	if not d.has(name):
		return
	var value: Variant = d[name]
	if typeof(value) != TYPE_ARRAY:
		errors.append("%s must be an array" % name)
		return
	if value.size() > max_items:
		errors.append("%s has too many items" % name)
	for index in value.size():
		var item: Variant = value[index]
		if typeof(item) != TYPE_STRING:
			errors.append("%s[%d] must be a string" % [name, index])
		elif str(item).is_empty() or str(item).length() > max_length:
			errors.append("%s[%d] length is out of range" % [name, index])


static func _check_unsaved_resources(d: Dictionary, name: String, errors: Array) -> void:
	if not d.has(name):
		return
	var value: Variant = d[name]
	if typeof(value) != TYPE_ARRAY:
		errors.append("%s must be an array" % name)
		return
	if value.size() > 500:
		errors.append("%s has too many items" % name)
	for index in value.size():
		var item: Variant = value[index]
		if typeof(item) != TYPE_DICTIONARY:
			errors.append("%s[%d] must be an object" % [name, index])
			continue
		for field in UNSAVED_RESOURCE_FIELDS:
			if not item.has(field):
				errors.append("%s[%d] missing required field: %s" % [name, index, field])
		_check_pattern_field(item, "path", RESOURCE_PATH_PATTERN, errors)
		if item.has("resource_type"):
			var resource_type: Variant = item["resource_type"]
			if typeof(resource_type) != TYPE_STRING:
				errors.append("resource_type must be a string")
			elif str(resource_type).is_empty() or str(resource_type).length() > 64:
				errors.append("resource_type length is out of range")
		_check_unknown(item, UNSAVED_RESOURCE_FIELDS, errors)


static func _check_pattern_field(d: Dictionary, name: String, pattern: String, errors: Array) -> void:
	if not d.has(name):
		return
	var value: Variant = d[name]
	if typeof(value) != TYPE_STRING or not _matches(str(value), pattern):
		errors.append("%s has invalid format" % name)


static func _check_timestamp_field(d: Dictionary, name: String, errors: Array) -> void:
	if not d.has(name):
		return
	var value: Variant = d[name]
	if typeof(value) != TYPE_STRING or not _matches(str(value), STARTED_AT_PATTERN):
		errors.append("%s must be an RFC3339 timestamp" % name)


static func _check_nullable_timestamp_field(d: Dictionary, name: String, errors: Array) -> void:
	if not d.has(name) or typeof(d[name]) == TYPE_NIL:
		return
	_check_timestamp_field(d, name, errors)


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
