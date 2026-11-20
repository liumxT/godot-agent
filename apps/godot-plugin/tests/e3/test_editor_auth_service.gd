@tool
extends "res://tests/test_case.gd"
## 认证辅助与凭证存储测试（E3-T06 客户端侧）。

const EditorAuth := preload("res://addons/godot_ai_agent/services/editor_auth_service.gd")
const CredentialsStore := preload("res://addons/godot_ai_agent/utilities/credentials_store.gd")

const TEST_PATH := "user://e3_test_credentials.json"
const SECRET := "test-secret"


func _init() -> void:
	suite_name = "t06_editor_auth"


## T06-UT-006：proof 与后端一致（固定测试向量），且为 base64url 无填充。
func test_proof_matches_backend_vector() -> void:
	var proof := EditorAuth.compute_proof(SECRET, "chl_00000001", "abcdef")
	assert_eq(proof, "8AYYWdKUQfG0Vsa8wV5yeMzTx2gydql3ctwOEg3cMl0")
	assert_false(proof.contains("+"))
	assert_false(proof.contains("/"))
	assert_false(proof.contains("="))


## T06-UT-007：HELLO 帧字段与契约一致，且不携带任何密钥。
func test_hello_frame_contains_project_and_versions() -> void:
	var frame := EditorAuth.make_hello(
		"cli_0000000001", "edi_0123456789ab", "/tmp/demo", "Demo", "4.5.1", "0.1.0"
	)
	assert_eq(str(frame["protocol_version"]), "1.0")
	assert_eq(str(frame["message_type"]), "HELLO")
	assert_true(str(frame["message_id"]).begins_with("ctl_"))
	assert_eq(str(frame["message_id"]).length(), 12)
	assert_eq(str(frame["payload"]["project"]["root"]), "/tmp/demo")
	assert_eq(str(frame["payload"]["editor_instance_id"]), "edi_0123456789ab")
	assert_false(JSON.stringify(frame).contains("secret"))


## T06-UT-008：挑战响应使用服务端下发的 challenge_id 与 challenge。
func test_auth_response_uses_challenge() -> void:
	var frame := EditorAuth.make_auth_response("chl_00000001", "abcdef", SECRET)
	assert_eq(str(frame["message_type"]), "AUTH_RESPONSE")
	assert_eq(str(frame["payload"]["challenge_id"]), "chl_00000001")
	assert_eq(str(frame["payload"]["proof"]), EditorAuth.compute_proof(SECRET, "chl_00000001", "abcdef"))
	assert_false(str(frame["payload"]["proof"]).is_empty())


## T06-UT-009：凭证往返保存与读取；mask 不泄露完整 secret。
func test_credentials_roundtrip_and_mask() -> void:
	var store = CredentialsStore.new(TEST_PATH)
	store.clear()
	assert_false(store.load_credentials())
	assert_eq(store.last_error(), "CREDENTIALS_MISSING")

	assert_true(store.save_credentials("cli_0000000001", "sec_abcdefghijklmnop"))
	assert_true(store.has_credentials())

	var reloaded = CredentialsStore.new(TEST_PATH)
	assert_true(reloaded.load_credentials())
	assert_eq(reloaded.client_id(), "cli_0000000001")
	assert_eq(reloaded.client_secret(), "sec_abcdefghijklmnop")

	var masked := CredentialsStore.mask(reloaded.client_secret())
	assert_false(masked.contains("abcdefghijklmnop"))
	assert_true(masked.contains("***"))

	store.clear()
	assert_false(FileAccess.file_exists(TEST_PATH))


## T06-UT-010：非法凭证文件返回 CREDENTIALS_CORRUPT 而不是抛出。
func test_corrupt_credentials_file() -> void:
	var file := FileAccess.open(TEST_PATH, FileAccess.WRITE)
	file.store_string("{not-json")
	file.close()

	var store = CredentialsStore.new(TEST_PATH)
	assert_false(store.load_credentials())
	assert_eq(store.last_error(), "CREDENTIALS_CORRUPT")
	store.clear()
