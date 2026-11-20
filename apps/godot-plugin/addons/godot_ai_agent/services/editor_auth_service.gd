@tool
extends RefCounted
## 客户端认证辅助（E3-T06）。
##
## 只生成握手帧与 HMAC proof，不持有连接、不存储凭证、不写日志。
## proof 与后端一致：base64url(HMAC-SHA256(secret, challenge_id + "." + challenge))。


const PROTOCOL_VERSION := "1.0"


## 生成控制帧外层结构，字段与 bridge/control.schema.json 对齐。
static func make_control(message_type: String, payload: Dictionary, correlation_id: String = "") -> Dictionary:
	return {
		"protocol_version": PROTOCOL_VERSION,
		"message_id": new_message_id(),
		"message_type": message_type,
		"timestamp": utc_timestamp(),
		"session_id": null,
		"project_id": null,
		"correlation_id": correlation_id if not correlation_id.is_empty() else null,
		"payload": payload,
	}


static func make_hello(
	client_id: String,
	editor_instance_id: String,
	project_root: String,
	project_name: String,
	godot_version: String,
	plugin_version: String,
	resume: Dictionary = {}
) -> Dictionary:
	var payload := {
		"client_id": client_id,
		"editor_instance_id": editor_instance_id,
		"plugin_version": plugin_version,
		"godot_version": godot_version,
		"project": {
			"root": project_root,
			"name": project_name,
			"godot_version": godot_version,
		},
	}
	if not resume.is_empty():
		payload["resume"] = {
			"session_id": str(resume.get("session_id", "")),
			"session_token": str(resume.get("session_token", "")),
		}
	return make_control("HELLO", payload)


static func make_auth_response(challenge_id: String, challenge: String, client_secret: String) -> Dictionary:
	return make_control("AUTH_RESPONSE", {
		"challenge_id": challenge_id,
		"proof": compute_proof(client_secret, challenge_id, challenge),
	})


## 计算 base64url 无填充的 HMAC-SHA256。
static func compute_proof(client_secret: String, challenge_id: String, challenge: String) -> String:
	var context := HMACContext.new()
	var err := context.start(HashingContext.HASH_SHA256, client_secret.to_utf8_buffer())
	if err != OK:
		return ""
	context.update(("%s.%s" % [challenge_id, challenge]).to_utf8_buffer())
	return _base64url(context.finish())


static func utc_timestamp() -> String:
	return Time.get_datetime_string_from_system(true) + "Z"


static func new_message_id() -> String:
	return "ctl_%08x" % (randi() % 0x100000000)


static func _base64url(bytes: PackedByteArray) -> String:
	return Marshalls.raw_to_base64(bytes).replace("+", "-").replace("/", "_").replace("=", "")
