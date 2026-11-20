@tool
extends RefCounted
## Bridge Action Registry（E3-T04）。
##
## 只登记 E3 实际落地的 action；未登记 action 一律拒绝，不得猜测执行。
## `editor.command.execute` 为 E5 预留，E3 返回 NOT_IMPLEMENTED。


const DIRECTION_PLUGIN_TO_BACKEND := "plugin_to_backend"
const DIRECTION_BACKEND_TO_PLUGIN := "backend_to_plugin"
const DIRECTION_BIDIRECTIONAL := "bidirectional"
const DIRECTION_RUNTIME_TO_BACKEND := "runtime_to_backend"

const PERMISSION_SESSION := "session"
const PERMISSION_SESSION_LEASE := "session_lease"
const PERMISSION_RUNTIME := "runtime"
const PERMISSION_RESERVED := "reserved"

const ACTION_HEARTBEAT := "session.heartbeat"
const ACTION_STATE_REPORT := "editor.state.report"
const ACTION_EVENTS_PUBLISH := "bridge.events.publish"
const ACTION_EVENTS_ACK := "bridge.events.ack"
const ACTION_EVENTS_SINCE := "bridge.events.since"
const ACTION_SNAPSHOT := "editor.snapshot"
const ACTION_SESSION_RECOVER := "bridge.session.recover"
const ACTION_RUNTIME_REPORT := "bridge.runtime.report"
const ACTION_COMMAND_EXECUTE := "editor.command.execute"

const ACTIONS := {
	ACTION_HEARTBEAT: {
		"direction": DIRECTION_PLUGIN_TO_BACKEND,
		"permission": PERMISSION_SESSION,
		"reserved": false,
	},
	ACTION_STATE_REPORT: {
		"direction": DIRECTION_PLUGIN_TO_BACKEND,
		"permission": PERMISSION_SESSION_LEASE,
		"reserved": false,
	},
	ACTION_EVENTS_PUBLISH: {
		"direction": DIRECTION_PLUGIN_TO_BACKEND,
		"permission": PERMISSION_SESSION,
		"reserved": false,
	},
	ACTION_EVENTS_ACK: {
		"direction": DIRECTION_PLUGIN_TO_BACKEND,
		"permission": PERMISSION_SESSION,
		"reserved": false,
	},
	ACTION_EVENTS_SINCE: {
		"direction": DIRECTION_PLUGIN_TO_BACKEND,
		"permission": PERMISSION_SESSION,
		"reserved": false,
	},
	ACTION_SNAPSHOT: {
		"direction": DIRECTION_BIDIRECTIONAL,
		"permission": PERMISSION_SESSION_LEASE,
		"reserved": false,
	},
	ACTION_SESSION_RECOVER: {
		"direction": DIRECTION_PLUGIN_TO_BACKEND,
		"permission": PERMISSION_SESSION,
		"reserved": false,
	},
	ACTION_RUNTIME_REPORT: {
		"direction": DIRECTION_RUNTIME_TO_BACKEND,
		"permission": PERMISSION_RUNTIME,
		"reserved": false,
	},
	ACTION_COMMAND_EXECUTE: {
		"direction": DIRECTION_BACKEND_TO_PLUGIN,
		"permission": PERMISSION_RESERVED,
		"reserved": true,
	},
}


static func has_action(action: String) -> bool:
	return ACTIONS.has(action)


static func is_reserved(action: String) -> bool:
	if not ACTIONS.has(action):
		return false
	return bool(ACTIONS[action]["reserved"])


static func get_direction(action: String) -> String:
	if not ACTIONS.has(action):
		return ""
	return str(ACTIONS[action]["direction"])


static func get_permission(action: String) -> String:
	if not ACTIONS.has(action):
		return ""
	return str(ACTIONS[action]["permission"])


static func all_actions() -> Array:
	var names: Array = ACTIONS.keys()
	names.sort()
	return names


## 返回空字符串表示允许；否则返回错误码。
static func check_action(action: String) -> String:
	if not has_action(action):
		return "UNKNOWN_MESSAGE_TYPE"
	if is_reserved(action):
		return "NOT_IMPLEMENTED"
	return ""
