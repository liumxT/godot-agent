@tool
extends "res://tests/test_case.gd"
## Editor Session 客户端服务测试（E3-T06/T07/T08 客户端侧）。

const EditorSessionService := preload("res://addons/godot_ai_agent/services/editor_session_service.gd")
const EditorAuth := preload("res://addons/godot_ai_agent/services/editor_auth_service.gd")
const PluginContext := preload("res://addons/godot_ai_agent/core/plugin_context.gd")
const CredentialsStore := preload("res://addons/godot_ai_agent/utilities/credentials_store.gd")
const LeaseModel := preload("res://addons/godot_ai_agent/models/lease.gd")
const FakeWsServer := preload("res://tests/e3/fakes/fake_ws_server.gd")

const CLIENT_ID := "cli_0000000001"
const CLIENT_SECRET := "test-secret"
const EDITOR_INSTANCE := "edi_0123456789ab"
const SESSION_ID := "ses_000000000001"
const PROJECT_ID := "prj_abcdefghijkl"


func _init() -> void:
	suite_name = "t07_editor_session"


func _save_credentials() -> void:
	CredentialsStore.new().save_credentials(CLIENT_ID, CLIENT_SECRET)


func _clear_credentials() -> void:
	CredentialsStore.new().clear()


func _make_context(port: int) -> Object:
	var ctx = PluginContext.new(null, "0.1.0", "4.5.1")
	ctx.set_config("backend_url", "http://127.0.0.1:%d" % port)
	ctx.set_config("auto_connect", false)
	ctx.set_config("project_root", ProjectSettings.globalize_path("res://"))
	ctx.set_config("project_name", "Demo")
	ctx.set_config("editor_instance_id", EDITOR_INSTANCE)
	return ctx


func _make_service(port: int):
	var service = EditorSessionService.new()
	assert_true(service.initialize(_make_context(port)))
	assert_true(service.start())
	return service


func _pump(service, check: Callable, server, iterations: int = 400) -> bool:
	for _step in iterations:
		server.poll()
		service.tick(0.01)
		if bool(check.call()):
			return true
		OS.delay_msec(2)
	return false


func _iso(offset_seconds: int = 0) -> String:
	return Time.get_datetime_string_from_unix_time(
		int(Time.get_unix_time_from_system()) + offset_seconds
	) + "Z"


func _control(message_type: String, payload: Dictionary) -> String:
	return JSON.stringify(EditorAuth.make_control(message_type, payload, "corr-e3"))


func _session_payload() -> Dictionary:
	return {
		"session_id": SESSION_ID,
		"session_token": "gds_" + "a".repeat(43),
		"token_type": "Bearer",
		"expires_at": _iso(1800),
		"editor_instance_id": EDITOR_INSTANCE,
		"project_id": PROJECT_ID,
		"lease": {
			"lease_id": "lea_000000000001",
			"session_id": SESSION_ID,
			"project_id": PROJECT_ID,
			"fencing_token": 1,
			"status": "ACTIVE",
			"issued_at": _iso(),
			"renewed_at": null,
			"expires_at": _iso(45),
			"revoked_at": null,
		},
		"heartbeat_interval_seconds": 10,
		"request_timeout_seconds": 15,
	}


## 完成 HELLO → AUTH_CHALLENGE → AUTH_RESPONSE → SESSION_CREATED。
func _complete_handshake(service, server) -> bool:
	assert_true(_pump(service, func(): return server.received_frames.size() >= 1, server))
	var hello: Variant = JSON.parse_string(str(server.received_frames[0]))
	if typeof(hello) != TYPE_DICTIONARY:
		return false
	assert_eq(str(hello.get("message_type", "")), "HELLO")
	assert_eq(str(hello["payload"]["client_id"]), CLIENT_ID)

	server.send_text(_control("AUTH_CHALLENGE", {
		"challenge_id": "chl_00000001",
		"challenge": "abcdef",
		"expires_at": _iso(60),
	}))
	assert_true(_pump(service, func(): return server.received_frames.size() >= 2, server))
	var auth: Variant = JSON.parse_string(str(server.received_frames[1]))
	if typeof(auth) != TYPE_DICTIONARY:
		return false
	assert_eq(str(auth.get("message_type", "")), "AUTH_RESPONSE")
	assert_eq(
		str(auth["payload"]["proof"]),
		EditorAuth.compute_proof(CLIENT_SECRET, "chl_00000001", "abcdef")
	)

	server.send_text(_control("SESSION_CREATED", _session_payload()))
	return _pump(service, func(): return service.is_session_connected(), server)


## T07-IT-001：完整握手后缓存 Session 与 Lease，并允许受保护操作。
func test_handshake_completes_and_caches_session() -> void:
	_save_credentials()
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)
	var service = _make_service(port)

	assert_true(service.request_connect())
	assert_true(_complete_handshake(service, server))

	var session: Dictionary = service.session_data()
	assert_eq(str(session["session_id"]), SESSION_ID)
	assert_eq(str(session["project_id"]), PROJECT_ID)
	assert_eq(service.fencing_token(), 1)
	assert_true(service.can_use_lease())
	assert_eq(str(service.status()["connection"]), "CONNECTED")
	assert_eq(str(service.status()["session_id"]), SESSION_ID)

	service.request_disconnect()
	assert_false(service.is_session_connected())
	assert_eq(service.connection_state(), "DISCONNECTED")
	service.stop("test")
	server.stop()
	_clear_credentials()


## T06-UT-011：认证挑战缺字段时不发送 AUTH_RESPONSE，并报错。
func test_invalid_challenge_is_rejected() -> void:
	_save_credentials()
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)
	var service = _make_service(port)
	var errors: Array = []
	service.error_raised.connect(func(code, _message): errors.append(code))

	assert_true(service.request_connect())
	assert_true(_pump(service, func(): return server.received_frames.size() >= 1, server))
	server.send_text(_control("AUTH_CHALLENGE", {"challenge_id": "chl_00000001"}))

	assert_true(_pump(service, func(): return errors.size() > 0, server))
	assert_eq(str(errors[0]), "CONTRACT_INVALID")
	assert_eq(server.received_frames.size(), 1)
	service.stop("test")
	server.stop()
	_clear_credentials()


## T07-UT-005：SESSION_CREATED 不符合契约时不得建立会话。
func test_invalid_session_created_is_rejected() -> void:
	_save_credentials()
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)
	var service = _make_service(port)
	var errors: Array = []
	service.error_raised.connect(func(code, _message): errors.append(code))

	assert_true(service.request_connect())
	assert_true(_pump(service, func(): return server.received_frames.size() >= 1, server))
	server.send_text(_control("AUTH_CHALLENGE", {
		"challenge_id": "chl_00000001",
		"challenge": "abcdef",
		"expires_at": _iso(60),
	}))
	assert_true(_pump(service, func(): return server.received_frames.size() >= 2, server))
	server.send_text(_control("SESSION_CREATED", {
		"session_id": SESSION_ID,
		"session_token": "gds_short",
		"token_type": "Bearer",
		"expires_at": _iso(1800),
		"editor_instance_id": EDITOR_INSTANCE,
		"project_id": PROJECT_ID,
		"lease": {"lease_id": "lea_000000000001"},
		"heartbeat_interval_seconds": 10,
		"request_timeout_seconds": 15,
	}))

	assert_true(_pump(service, func(): return errors.size() > 0, server))
	assert_eq(str(errors[0]), "CONTRACT_INVALID")
	assert_false(service.is_session_connected())
	assert_true(service.session_data().is_empty())
	service.stop("test")
	server.stop()
	_clear_credentials()


## T06-UT-012：缺少凭证时拒绝连接且不发起网络请求。
func test_missing_credentials_blocks_connect() -> void:
	_clear_credentials()
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)
	var service = _make_service(port)
	var errors: Array = []
	service.error_raised.connect(func(code, _message): errors.append(code))

	assert_false(service.request_connect())
	assert_eq(service.connection_state(), "DISCONNECTED")
	assert_eq(str(errors[0]), "CREDENTIALS_MISSING")
	assert_eq(server.upgraded_client_count(), 0)
	service.stop("test")
	server.stop()


## T08-UT-007：租约模型解析和本地可用性判断。
func test_lease_model_parsing() -> void:
	var lease := LeaseModel.parse(_session_payload()["lease"])
	assert_false(lease.is_empty())
	assert_eq(int(lease["fencing_token"]), 1)
	assert_true(LeaseModel.is_usable(lease))
	assert_true(LeaseModel.remaining_seconds(lease) > 0)

	var expired := lease.duplicate(true)
	expired["expires_at"] = _iso(-1)
	assert_false(LeaseModel.is_usable(expired))

	var revoked := lease.duplicate(true)
	revoked["status"] = "REVOKED"
	assert_false(LeaseModel.is_usable(revoked))

	assert_true(LeaseModel.parse({"lease_id": "lea_x"}).is_empty())
