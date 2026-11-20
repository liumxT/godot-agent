@tool
extends "res://tests/test_case.gd"
## E3-T05 WebSocket Client 测试（T05-UT-001…005、T05-IT-001）。

const EditorBridgeClient := preload("res://addons/godot_ai_agent/bridge/editor_bridge_client.gd")
const FakeWsServer := preload("res://tests/e3/fakes/fake_ws_server.gd")


func _init() -> void:
	suite_name = "t05_editor_bridge_client"


func _make_client(port: int, queue_max: int = 64):
	var client = EditorBridgeClient.new()
	client.setup("ws://127.0.0.1:%d/api/v1/ws/editor" % port, 10.0, queue_max)
	return client


func _request_frame(action: String) -> Dictionary:
	return {
		"protocol_version": "1.0",
		"request_id": "req_000000000001",
		"timestamp": "2026-11-18T09:00:00Z",
		"action": action,
		"payload": {},
	}


func _pump(client, check: Callable, server = null, iterations: int = 400) -> bool:
	for _step in iterations:
		if server != null and server.has_method("poll"):
			server.call("poll")
		client.poll(0.01)
		if bool(check.call()):
			return true
		OS.delay_msec(2)
	return false


## T05-UT-001：连接成功进入 CONNECTED。
func test_connect_success() -> void:
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)

	var client = _make_client(port)
	client.connect_to_backend()
	assert_eq(client.get_state(), "CONNECTING")
	assert_true(_pump(client, func(): return client.get_state() == "CONNECTED", server))
	assert_true(client.is_open())

	client.close()
	server.stop()


## T05-UT-002：连接失败进入 CONNECTION_LOST 且可重连。
func test_connect_failure() -> void:
	var placeholder := FakeWsServer.new()
	var port := placeholder.start()
	assert_true(port > 0)
	placeholder.stop()

	var client = EditorBridgeClient.new()
	client.setup("ws://127.0.0.1:%d/api/v1/ws/editor" % port, 0.2)
	client.connect_to_backend()
	assert_true(
		_pump(client, func(): return client.get_state() != "CONNECTING", null, 60),
		"握手超时后应离开 CONNECTING"
	)
	assert_false(client.is_open())
	assert_eq(client.get_state(), "CONNECTION_LOST")
	assert_eq(client.last_close_code(), 4408)


## T05-UT-003：消息发送经协议编码后写入连接。
func test_send_message() -> void:
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)

	var client = _make_client(port)
	client.connect_to_backend()
	assert_true(_pump(client, func(): return client.is_open(), server))

	assert_true(client.send_frame(_request_frame("session.heartbeat")))
	assert_true(_pump(client, func(): return server.received_frames.size() > 0, server))
	var parsed: Variant = JSON.parse_string(str(server.received_frames[0]))
	assert_true(typeof(parsed) == TYPE_DICTIONARY)
	assert_eq(str(parsed.get("action", "")), "session.heartbeat")

	server.stop()


## T05-UT-004：接收消息并通过信号抛出。
func test_receive_message() -> void:
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)

	var client = _make_client(port)
	var received: Array = []
	client.frame_received.connect(func(kind, frame): received.append({"kind": kind, "frame": frame}))
	client.connect_to_backend()
	assert_true(_pump(client, func(): return client.is_open(), server))

	server.send_text(JSON.stringify({
		"protocol_version": "1.0",
		"request_id": "req_000000000001",
		"success": true,
		"data": {"server_time": "2026-11-18T09:00:01Z"},
		"error": null,
	}))
	assert_true(_pump(client, func(): return received.size() > 0, server))
	assert_eq(str(received[0]["kind"]), "response")
	assert_eq(str(received[0]["frame"]["request_id"]), "req_000000000001")

	server.stop()


## T05-UT-005：非法消息只记错误，不破坏连接。
func test_invalid_message() -> void:
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)

	var client = _make_client(port)
	var errors: Array = []
	client.protocol_error.connect(func(code, _message): errors.append(code))
	client.connect_to_backend()
	assert_true(_pump(client, func(): return client.is_open(), server))

	server.send_text('{"message_type":"PING"}')
	assert_true(_pump(client, func(): return errors.size() > 0, server))
	assert_eq(str(errors[0]), "UNKNOWN_MESSAGE_TYPE")
	assert_true(client.is_open())

	server.stop()


## T05-IT-001：双向通信（发请求 + 收响应）。
func test_it_bidirectional_communication() -> void:
	var server := FakeWsServer.new()
	var port := server.start()
	assert_true(port > 0)

	var client = _make_client(port)
	var received: Array = []
	client.frame_received.connect(func(kind, frame): received.append({"kind": kind, "frame": frame}))
	client.connect_to_backend()
	assert_true(_pump(client, func(): return client.is_open(), server))

	assert_true(client.send_frame(_request_frame("bridge.events.ack")))
	assert_true(_pump(client, func(): return server.received_frames.size() > 0, server))
	var request: Variant = JSON.parse_string(str(server.received_frames[0]))
	assert_eq(str(request.get("action", "")), "bridge.events.ack")

	server.send_text(JSON.stringify({
		"protocol_version": "1.0",
		"request_id": "req_000000000001",
		"success": true,
		"data": {"acked": 1},
		"error": null,
	}))
	assert_true(_pump(client, func(): return received.size() > 0, server))
	assert_eq(str(received[0]["kind"]), "response")

	server.stop()


## 队列上限：EPHEMERAL 先丢弃，PERSISTENT 保留并标记 unsynced。
func test_queue_overflow() -> void:
	var client = _make_client(1, 2)
	var frame := _request_frame("session.heartbeat")

	assert_true(client.send_frame(frame, "EPHEMERAL"))
	assert_true(client.send_frame(frame, "EPHEMERAL"))
	assert_false(client.send_frame(frame, "EPHEMERAL"))
	assert_eq(client.pending_count(), 2)
	assert_eq(client.dropped_count(), 1)

	# PERSISTENT 入队时优先挤掉队列中已有的 EPHEMERAL。
	assert_true(client.send_frame(frame, "PERSISTENT"))
	assert_eq(client.pending_count(), 2)
	assert_eq(client.dropped_count(), 2)
	assert_true(client.send_frame(frame, "PERSISTENT"))
	assert_eq(client.pending_count(), 2)
	assert_eq(client.dropped_count(), 3)
	assert_false(client.has_unsynced())

	# 队列已全部为 PERSISTENT 时，新 PERSISTENT 被拒并标记 unsynced。
	assert_false(client.send_frame(frame, "PERSISTENT"))
	assert_true(client.has_unsynced())
	assert_eq(client.dropped_count(), 4)
