@tool
extends "res://tests/test_case.gd"
## E3-T04 Bridge 协议适配器测试（T04-UT-001…004）。

const ProtocolAdapter := preload("res://addons/godot_ai_agent/bridge/protocol_adapter.gd")
const ActionRegistry := preload("res://addons/godot_ai_agent/bridge/action_registry.gd")


func _init() -> void:
	suite_name = "t04_protocol_adapter"


func _control_frame() -> Dictionary:
	return {
		"protocol_version": "1.0",
		"message_id": "ctl_7f3a9c2e",
		"message_type": "HELLO",
		"timestamp": "2026-11-18T09:00:00Z",
		"session_id": null,
		"project_id": null,
		"correlation_id": null,
		"payload": {},
	}


func _request_frame(action: String) -> Dictionary:
	return {
		"protocol_version": "1.0",
		"request_id": "req_000000000001",
		"timestamp": "2026-11-18T09:00:00Z",
		"action": action,
		"payload": {},
	}


## T04-UT-001：控制帧编解码与契约校验。
func test_control_frame_roundtrip() -> void:
	var adapter := ProtocolAdapter.new()
	var decoded := adapter.decode_text(JSON.stringify(_control_frame()))
	assert_true(bool(decoded["ok"]))
	assert_eq(str(decoded["kind"]), "control")
	assert_eq(str(decoded["message_type"]), "HELLO")

	var encoded := adapter.encode_frame(_control_frame())
	assert_true(bool(encoded["ok"]))
	var parsed: Variant = JSON.parse_string(str(encoded["text"]))
	assert_true(typeof(parsed) == TYPE_DICTIONARY)
	assert_eq(str(parsed.get("message_type", "")), "HELLO")


## T04-UT-002：未知消息类型与非法 JSON 被拒绝且不触发关闭。
func test_unknown_message_type_rejected() -> void:
	var adapter := ProtocolAdapter.new()
	var decoded := adapter.decode_text('{"message_type":"PING"}')
	assert_false(bool(decoded["ok"]))
	assert_eq(str(decoded["error_code"]), "UNKNOWN_MESSAGE_TYPE")
	assert_eq(int(decoded["close_code"]), 0)

	var invalid := adapter.decode_text("not-json")
	assert_false(bool(invalid["ok"]))
	assert_eq(str(invalid["error_code"]), "INVALID_REQUEST")
	assert_eq(adapter.invalid_count(), 2)


## T04-UT-003：单帧上限 256 KiB，超限返回 REQUEST_TOO_LARGE 与关闭码 4409。
func test_oversize_frame_rejected() -> void:
	var adapter := ProtocolAdapter.new()
	var huge := "x".repeat(ProtocolAdapter.MAX_MESSAGE_BYTES + 1)

	var decoded := adapter.decode_text('{"message_type":"HELLO","blob":"%s"}' % huge)
	assert_false(bool(decoded["ok"]))
	assert_eq(str(decoded["error_code"]), "REQUEST_TOO_LARGE")
	assert_eq(int(decoded["close_code"]), 4409)

	var encoded := adapter.encode_frame({"payload": {"blob": huge}})
	assert_false(bool(encoded["ok"]))
	assert_eq(str(encoded["error_code"]), "REQUEST_TOO_LARGE")
	assert_eq(int(encoded["close_code"]), 4409)


## T04-UT-004：未登记 action 拒绝，预留 action 返回 NOT_IMPLEMENTED。
func test_unknown_and_reserved_action() -> void:
	var adapter := ProtocolAdapter.new()

	var accepted := adapter.decode_text(JSON.stringify(_request_frame("session.heartbeat")))
	assert_true(bool(accepted["ok"]))
	assert_eq(str(accepted["kind"]), "request")
	assert_eq(str(accepted["action"]), "session.heartbeat")

	var unknown := adapter.decode_text(JSON.stringify(_request_frame("editor.get_state")))
	assert_false(bool(unknown["ok"]))
	assert_eq(str(unknown["error_code"]), "UNKNOWN_MESSAGE_TYPE")

	var reserved := adapter.decode_text(JSON.stringify(_request_frame("editor.command.execute")))
	assert_false(bool(reserved["ok"]))
	assert_eq(str(reserved["error_code"]), "NOT_IMPLEMENTED")

	assert_true(ActionRegistry.is_reserved("editor.command.execute"))
	assert_eq(ActionRegistry.get_permission("editor.state.report"), "session_lease")
	assert_eq(ActionRegistry.get_direction("bridge.runtime.report"), "runtime_to_backend")
