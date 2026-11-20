@tool
extends "res://tests/test_case.gd"
## Runtime Bridge 测试（E3-T16 客户端侧，无网络）。

const RuntimeBridge := preload("res://addons/godot_ai_agent/runtime/runtime_bridge.gd")
const EditorAuth := preload("res://addons/godot_ai_agent/services/editor_auth_service.gd")
const ProtocolAdapter := preload("res://addons/godot_ai_agent/bridge/protocol_adapter.gd")
const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")

const CLIENT_ID := "cli_aaaaaaaaaaaa"
const RUNTIME_ID := "rti_0123456789ab"
const FINGERPRINT := "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


func _init() -> void:
	suite_name = "t16_runtime_bridge"


## T16-UT-001：Runtime 注册载荷符合契约，路径只以指纹暴露。
func test_registration_payload() -> void:
	var hello := RuntimeBridge.build_hello_payload(
		CLIENT_ID,
		RUNTIME_ID,
		FINGERPRINT,
		OS.get_process_id(),
		RuntimeBridge.utc_timestamp(),
		"4.5.1.stable"
	)
	assert_eq(str(hello["project_root"]), "res://")
	assert_eq(str(hello["client_id"]), CLIENT_ID)
	assert_eq(str(hello["runtime_instance_id"]), RUNTIME_ID)
	assert_eq(str(hello["build_mode"]), "debug")
	assert_eq(str(hello["status"]), "RUNNING")

	var report_state := hello.duplicate(true)
	report_state.erase("client_id")
	assert_eq(Validator.validate_bridge_runtime(report_state), [])


## T16-UT-002：Runtime 认证复用 E2 挑战，控制帧契约接受 RUNTIME_REGISTERED。
func test_authentication_frames() -> void:
	var hello := RuntimeBridge.make_hello(
		CLIENT_ID,
		RUNTIME_ID,
		FINGERPRINT,
		OS.get_process_id(),
		RuntimeBridge.utc_timestamp(),
		"4.5.1.stable"
	)
	assert_eq(Validator.validate_bridge_control(hello), [])

	var auth := EditorAuth.make_auth_response("chl_0123456789ab", "challenge-value", "secret")
	assert_eq(Validator.validate_bridge_control(auth), [])
	var proof := str(auth["payload"]["proof"])
	assert_eq(proof.length(), 43, "HMAC-SHA256 base64url 无填充长度")
	assert_eq(proof, EditorAuth.compute_proof("secret", "chl_0123456789ab", "challenge-value"))

	var registered := EditorAuth.make_control("RUNTIME_REGISTERED", {
		"runtime_instance_id": RUNTIME_ID,
		"status": "RUNNING",
	})
	var decoded: Dictionary = ProtocolAdapter.new().decode_text(JSON.stringify(registered))
	assert_true(bool(decoded["ok"]))
	assert_eq(str(decoded["kind"]), "control")


## T16-UT-003：停止上报使用标准 request 帧并携带 STOPPED。
func test_stop_report_frame() -> void:
	var frame := RuntimeBridge.make_report_frame(RUNTIME_ID, "STOPPED")
	assert_eq(str(frame["action"]), "bridge.runtime.report")
	assert_eq(Validator.validate_request(frame), [])
	assert_eq(str(frame["payload"]["status"]), "STOPPED")
	assert_eq(str(frame["payload"]["runtime_instance_id"]), RUNTIME_ID)
	assert_true(str(frame["payload"]["timestamp"]).ends_with("Z"))


## T16-UT-004：实例标识格式稳定，指纹与 URL 归一化可重复。
func test_identity_and_url_helpers() -> void:
	var runtime_id := RuntimeBridge.new_runtime_instance_id()
	assert_true(runtime_id.begins_with("rti_"))
	assert_eq(runtime_id.length(), 16, "rti_ + 12 位十六进制")

	var root := ProjectSettings.globalize_path("res://")
	var first := RuntimeBridge.project_fingerprint(root)
	var second := RuntimeBridge.project_fingerprint(root + "/")
	assert_eq(first.length(), 64, "sha256 十六进制摘要")
	assert_eq(first, second, "尾部斜杠不应改变指纹")
	assert_eq(RuntimeBridge.normalize_path("D:/demo/project/"), RuntimeBridge.normalize_path("D:\\demo\\project"))

	assert_eq(
		RuntimeBridge.to_runtime_url("http://127.0.0.1:8765"),
		"ws://127.0.0.1:8765/api/v1/ws/runtime"
	)
	assert_eq(
		RuntimeBridge.to_runtime_url("ws://127.0.0.1:8765/api/v1/ws/runtime"),
		"ws://127.0.0.1:8765/api/v1/ws/runtime"
	)
