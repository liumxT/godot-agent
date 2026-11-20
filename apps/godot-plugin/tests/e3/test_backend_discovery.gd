@tool
extends "res://tests/test_case.gd"
## E3-T03 Backend Discovery 测试（T03-UT-001…005、T03-IT-001）。

const BackendDiscovery := preload("res://addons/godot_ai_agent/services/backend_discovery_service.gd")
const Backoff := preload("res://addons/godot_ai_agent/utilities/backoff.gd")
const FakeHttpServer := preload("res://tests/e3/fakes/fake_http_server.gd")


func _init() -> void:
	suite_name = "t03_backend_discovery"


## T03-UT-001：地址优先级 EditorSettings → 环境变量 → 默认值。
func test_url_precedence() -> void:
	assert_eq(
		BackendDiscovery.resolve_backend_url(
			"http://127.0.0.1:9000", "http://127.0.0.1:9001", "http://127.0.0.1:8765"
		),
		"http://127.0.0.1:9000"
	)
	assert_eq(
		BackendDiscovery.resolve_backend_url(
			"   ", "http://127.0.0.1:9001", "http://127.0.0.1:8765"
		),
		"http://127.0.0.1:9001"
	)
	assert_eq(
		BackendDiscovery.resolve_backend_url("", "", "http://127.0.0.1:8765"),
		"http://127.0.0.1:8765"
	)


## T03-UT-002：仅允许回环 http 地址。
func test_loopback_validation() -> void:
	assert_true(BackendDiscovery.is_loopback_url("http://127.0.0.1:8765"))
	assert_true(BackendDiscovery.is_loopback_url("http://localhost:8765"))
	assert_false(BackendDiscovery.is_loopback_url("http://192.168.1.10:8765"))
	assert_false(BackendDiscovery.is_loopback_url("https://127.0.0.1:8765"))
	assert_false(BackendDiscovery.is_loopback_url("http://127.0.0.1:notaport"))
	assert_false(BackendDiscovery.is_loopback_url(""))


## T03-UT-003：六种结果码分类。
func test_result_classification() -> void:
	assert_eq(
		BackendDiscovery.classify_probe(BackendDiscovery.STATUS_REFUSED, 0, "", ""),
		BackendDiscovery.RESULT_NOT_STARTED
	)
	assert_eq(
		BackendDiscovery.classify_probe(BackendDiscovery.STATUS_UNREACHABLE, 0, "", ""),
		BackendDiscovery.RESULT_UNREACHABLE
	)
	assert_eq(BackendDiscovery.classify_probe(503, 0, "", ""), BackendDiscovery.RESULT_STARTING)
	assert_eq(
		BackendDiscovery.classify_probe(200, 500, "v1", "1.0"),
		BackendDiscovery.RESULT_STARTING
	)
	assert_eq(
		BackendDiscovery.classify_probe(200, 200, "v2", "1.0"),
		BackendDiscovery.RESULT_INCOMPATIBLE
	)
	assert_eq(
		BackendDiscovery.classify_probe(200, 200, "v1", "2.0"),
		BackendDiscovery.RESULT_INCOMPATIBLE
	)
	assert_eq(BackendDiscovery.classify_probe(200, 200, "v1", "1.0"), BackendDiscovery.RESULT_READY)


## T03-UT-004：退避序列、抖动范围与重置。
func test_backoff_sequence() -> void:
	var backoff := Backoff.new()
	backoff.set_seed(20261118)
	var bases: Array = [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]
	for base in bases:
		var delay := backoff.next_delay()
		assert_true(delay >= float(base) * 0.8 - 0.0001, "退避不得低于 -20%%")
		assert_true(delay <= float(base) * 1.2 + 0.0001, "退避不得高于 +20%%")
	backoff.reset()
	assert_eq(backoff.attempt_index(), 0)
	var first := backoff.next_delay()
	assert_true(first >= 0.4 and first <= 0.6)


## T03-UT-005：非法地址立即给出结果且服务保持运行。
func test_invalid_url_lifecycle() -> void:
	var service = BackendDiscovery.new()
	assert_true(service.initialize(null))
	service.set_backend_url("http://example.com:8765")
	assert_true(service.start())
	service.tick(0.016)
	assert_eq(service.get_result(), BackendDiscovery.RESULT_INVALID_URL)
	assert_true(service.is_running())
	service.stop()
	assert_eq(service.get_state(), "STOPPED")


## T03-IT-001：真实 TCP/HTTP 路径探测到 BACKEND_READY。
func test_it_discovery_ready_against_http_stub() -> void:
	var server := FakeHttpServer.new()
	var port := server.start()
	assert_true(port > 0)
	server.set_json("/api/v1/health/live", 200, '{"status":"ok"}')
	server.set_json(
		"/api/v1/system/info",
		200,
		'{"app_name":"godot-ai-agent","app_version":"0.1.0","api_version":"v1",'
		+ '"protocol_version":"1.0","environment":"test"}'
	)

	var service = BackendDiscovery.new()
	assert_true(service.initialize(null))
	service.set_backend_url("http://127.0.0.1:%d" % port)
	assert_true(service.start())

	for step in 1600:
		server.poll()
		service.tick(0.01)
		if not service.get_result().is_empty():
			break
		OS.delay_msec(2)

	assert_eq(
		service.get_result(),
		BackendDiscovery.RESULT_READY,
		"phase=%s" % service.get_phase()
	)
	service.stop()
	server.stop()
