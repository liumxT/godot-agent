@tool
extends RefCounted
## 最小 HTTP/1.1 测试服务端（仅 E3 测试使用）。
##
## 只解析请求行并返回预置 JSON，用于验证 Discovery 的真实 TCP/HTTP 路径。


var port := 0

var _server := TCPServer.new()
var _clients: Array = []
var _responses: Dictionary = {}


func start(port_hint: int = 0) -> int:
	for attempt in 20:
		var candidate := port_hint if port_hint > 0 else 20000 + (randi() % 20000)
		if _server.listen(candidate, "127.0.0.1") == OK:
			port = candidate
			return port
	return 0


func set_json(path: String, status: int, body: String) -> void:
	_responses[path] = {"status": status, "body": body}


func stop() -> void:
	for client in _clients:
		var peer: StreamPeerTCP = client["peer"]
		peer.disconnect_from_host()
	_clients.clear()
	_server.stop()
	port = 0


func poll() -> void:
	while _server.is_connection_available():
		var peer := _server.take_connection()
		if peer != null:
			_clients.append({"peer": peer, "buffer": ""})

	var alive: Array = []
	for client in _clients:
		var peer: StreamPeerTCP = client["peer"]
		peer.poll()
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			continue
		var available := peer.get_available_bytes()
		if available > 0:
			var chunk := peer.get_partial_data(available)
			if int(chunk[0]) == OK:
				client["buffer"] = str(client["buffer"]) + (chunk[1] as PackedByteArray).get_string_from_utf8()
		if str(client["buffer"]).find("\r\n\r\n") == -1:
			alive.append(client)
			continue
		var request_line := str(client["buffer"]).split("\r\n")[0]
		var parts := request_line.split(" ")
		var path := parts[1] if parts.size() > 1 else "/"
		var spec: Dictionary = _responses.get(path, {"status": 404, "body": "{}"})
		var body := str(spec["body"])
		var response := "HTTP/1.1 %d OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % [
			int(spec["status"]), body.to_utf8_buffer().size(), body,
		]
		peer.put_data(response.to_utf8_buffer())
		client["buffer"] = ""
		alive.append(client)
	_clients = alive
