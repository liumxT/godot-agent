@tool
extends RefCounted
## 最小 WebSocket 服务端（仅 E3 测试使用）。
##
## 支持 HTTP Upgrade、文本帧收发与超长帧，用于验证 WebSocketPeer 的真实收发路径。
## 不支持分片、压缩与二进制帧，满足 E3 测试需要即可。


var port := 0
var received_frames: Array = []

var _server := TCPServer.new()
var _clients: Array = []


func start(port_hint: int = 0) -> int:
	for attempt in 20:
		var candidate := port_hint if port_hint > 0 else 20000 + (randi() % 20000)
		if _server.listen(candidate, "127.0.0.1") == OK:
			port = candidate
			return port
	return 0


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
			_clients.append({
				"peer": peer,
				"buffer": "",
				"bytes": PackedByteArray(),
				"upgraded": false,
			})

	var alive: Array = []
	for client in _clients:
		var peer: StreamPeerTCP = client["peer"]
		peer.poll()
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			continue
		if not bool(client["upgraded"]):
			_read_http(client)
		if bool(client["upgraded"]):
			_read_frames(client)
		alive.append(client)
	_clients = alive


func send_text(text: String) -> void:
	for client in _clients:
		if bool(client["upgraded"]):
			_write_frame(client, text)


func upgraded_client_count() -> int:
	var count := 0
	for client in _clients:
		if bool(client["upgraded"]):
			count += 1
	return count


func _read_http(client: Dictionary) -> void:
	var available := _read_available(client)
	if available.is_empty():
		return
	client["buffer"] = str(client["buffer"]) + available.get_string_from_utf8()
	var text := str(client["buffer"])
	if text.find("\r\n\r\n") == -1:
		return
	var key := ""
	for line in text.split("\r\n"):
		if line.to_lower().begins_with("sec-websocket-key:"):
			key = line.substr(line.find(":") + 1).strip_edges()
	var response := "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % _accept_key(key)
	var peer: StreamPeerTCP = client["peer"]
	peer.put_data(response.to_utf8_buffer())
	client["upgraded"] = true
	client["buffer"] = ""


func _read_frames(client: Dictionary) -> void:
	var incoming := _read_available(client)
	if not incoming.is_empty():
		var merged: PackedByteArray = client["bytes"]
		merged.append_array(incoming)
		client["bytes"] = merged
	var buffer: PackedByteArray = client["bytes"]
	var offset := 0
	while buffer.size() - offset >= 2:
		var first := buffer[offset]
		var second := buffer[offset + 1]
		var opcode := first & 0x0F
		var masked := (second & 0x80) != 0
		var length := second & 0x7F
		var header := 2
		if length == 126:
			if buffer.size() - offset < 4:
				break
			length = (buffer[offset + 2] << 8) | buffer[offset + 3]
			header = 4
		elif length == 127:
			if buffer.size() - offset < 10:
				break
			length = 0
			for index in 8:
				length = (length << 8) | buffer[offset + 2 + index]
			header = 10
		var mask_length := 4 if masked else 0
		var total := header + mask_length + length
		if buffer.size() - offset < total:
			break
		var payload := buffer.slice(offset + header + mask_length, offset + total)
		if masked:
			for index in payload.size():
				payload[index] = payload[index] ^ buffer[offset + header + (index % 4)]
		if opcode == 0x1:
			received_frames.append(payload.get_string_from_utf8())
		offset += total
	client["bytes"] = buffer.slice(offset)


func _read_available(client: Dictionary) -> PackedByteArray:
	var peer: StreamPeerTCP = client["peer"]
	var available := peer.get_available_bytes()
	if available <= 0:
		return PackedByteArray()
	var chunk := peer.get_partial_data(available)
	if int(chunk[0]) != OK:
		return PackedByteArray()
	return chunk[1] as PackedByteArray


func _write_frame(client: Dictionary, text: String) -> void:
	var payload := text.to_utf8_buffer()
	var header := PackedByteArray()
	header.append(0x81)
	if payload.size() < 126:
		header.append(payload.size())
	elif payload.size() <= 65535:
		header.append(126)
		header.append((payload.size() >> 8) & 0xFF)
		header.append(payload.size() & 0xFF)
	else:
		header.append(127)
		for shift in [56, 48, 40, 32, 24, 16, 8, 0]:
			header.append((payload.size() >> shift) & 0xFF)
	var peer: StreamPeerTCP = client["peer"]
	var frame := header.duplicate()
	frame.append_array(payload)
	peer.put_data(frame)


func _accept_key(key: String) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA1)
	context.update((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").to_utf8_buffer())
	return Marshalls.raw_to_base64(context.finish())
