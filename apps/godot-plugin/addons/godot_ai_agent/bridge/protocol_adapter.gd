@tool
extends RefCounted
## Bridge 协议适配器（E3-T04）。
##
## 负责帧分类、契约校验、大小限制与错误码映射。
## 不持有连接、不读写 Session，也不处理 UI。


const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")
const ActionRegistry := preload("res://addons/godot_ai_agent/bridge/action_registry.gd")

const MAX_MESSAGE_BYTES := 262144
const CLOSE_NONE := 0
const CLOSE_MESSAGE_TOO_LARGE := 4409

const CONTROL_TYPES := [
	"HELLO", "AUTH_CHALLENGE", "AUTH_RESPONSE", "SESSION_CREATED", "RUNTIME_REGISTERED", "ERROR",
]

const KIND_CONTROL := "control"
const KIND_REQUEST := "request"
const KIND_RESPONSE := "response"
const KIND_EVENT := "event"

var _invalid_count := 0


func invalid_count() -> int:
	return _invalid_count


## 解析文本帧。返回字典：
## {ok, kind, message_type, action, request_id, frame, error_code, error_message, close_code}
func decode_text(text: String) -> Dictionary:
	if text.to_utf8_buffer().size() > MAX_MESSAGE_BYTES:
		return _reject_with_close(
			"REQUEST_TOO_LARGE", "frame exceeds 256 KiB", CLOSE_MESSAGE_TOO_LARGE
		)
	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		return _reject("INVALID_REQUEST", "frame is not a JSON object")
	return decode_frame(parsed)


func decode_frame(frame: Dictionary) -> Dictionary:
	var message_type := str(frame.get("message_type", ""))
	if not message_type.is_empty():
		return _decode_control(frame, message_type)

	if frame.has("success"):
		var response_errors: Array = Validator.validate_response(frame)
		if not response_errors.is_empty():
			return _reject("INVALID_REQUEST", str(response_errors[0]))
		return _accept(KIND_RESPONSE, frame, "", str(frame.get("request_id", "")))

	if frame.has("event_id"):
		var event_errors: Array = Validator.validate_event(frame)
		if not event_errors.is_empty():
			return _reject("INVALID_REQUEST", str(event_errors[0]))
		return _accept(KIND_EVENT, frame, "", "")

	if frame.has("request_id") and frame.has("action"):
		var request_errors: Array = Validator.validate_request(frame)
		if not request_errors.is_empty():
			return _reject("INVALID_REQUEST", str(request_errors[0]))
		var action := str(frame["action"])
		var action_error := ActionRegistry.check_action(action)
		if action_error == "NOT_IMPLEMENTED":
			return _reject("NOT_IMPLEMENTED", "action is reserved: %s" % action)
		if not action_error.is_empty():
			return _reject("UNKNOWN_MESSAGE_TYPE", "unregistered action: %s" % action)
		return _accept(KIND_REQUEST, frame, action, str(frame["request_id"]))

	return _reject("UNKNOWN_MESSAGE_TYPE", "unrecognized frame")


## 编码出站帧；超限时返回 REQUEST_TOO_LARGE 与关闭码 4409。
func encode_frame(frame: Dictionary) -> Dictionary:
	var text := JSON.stringify(frame)
	if text.to_utf8_buffer().size() > MAX_MESSAGE_BYTES:
		return _reject_with_close(
			"REQUEST_TOO_LARGE", "outbound frame exceeds 256 KiB", CLOSE_MESSAGE_TOO_LARGE
		)
	var result := _accept("", frame, "", "")
	result["text"] = text
	return result


func _decode_control(frame: Dictionary, message_type: String) -> Dictionary:
	if not CONTROL_TYPES.has(message_type):
		return _reject("UNKNOWN_MESSAGE_TYPE", "unknown control message_type: %s" % message_type)
	var errors: Array = Validator.validate_bridge_control(frame)
	if not errors.is_empty():
		return _reject("INVALID_REQUEST", str(errors[0]))
	return _accept(KIND_CONTROL, frame, "", "")


func _accept(kind: String, frame: Dictionary, action: String, request_id: String) -> Dictionary:
	return {
		"ok": true,
		"kind": kind,
		"message_type": str(frame.get("message_type", "")),
		"action": action,
		"request_id": request_id,
		"frame": frame,
		"error_code": "",
		"error_message": "",
		"close_code": CLOSE_NONE,
	}


func _reject(code: String, message: String) -> Dictionary:
	return _reject_with_close(code, message, CLOSE_NONE)


func _reject_with_close(code: String, message: String, close_code: int) -> Dictionary:
	_invalid_count += 1
	return {
		"ok": false,
		"kind": "",
		"message_type": "",
		"action": "",
		"request_id": "",
		"frame": {},
		"error_code": code,
		"error_message": message,
		"close_code": close_code,
	}
