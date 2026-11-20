@tool
extends RefCounted
## Editor Bridge WebSocket 客户端（E3-T05）。
##
## 只负责连接、收发与状态机，不持有 Session/项目/UI 状态。
## 必须由外部每帧调用 poll()；所有等待都是非阻塞的。


signal state_changed(previous: String, current: String)
signal frame_received(kind: String, frame: Dictionary)
signal connection_closed(code: int, reason: String, reconnect: bool)
signal protocol_error(code: String, message: String)

const ConnectionState := preload("res://addons/godot_ai_agent/bridge/connection_state.gd")
const ProtocolAdapter := preload("res://addons/godot_ai_agent/bridge/protocol_adapter.gd")

const DEFAULT_HANDSHAKE_TIMEOUT := 10.0
const CLOSING_TIMEOUT := 2.0
const DEFAULT_QUEUE_MAX := 64
const MAX_PACKETS_PER_POLL := 64

const DELIVERY_EPHEMERAL := "EPHEMERAL"
const DELIVERY_PERSISTENT := "PERSISTENT"

var _state := ConnectionState.DISCONNECTED
var _url := ""
var _peer: WebSocketPeer = null
var _handshake_timeout := DEFAULT_HANDSHAKE_TIMEOUT
var _queue_max := DEFAULT_QUEUE_MAX
var _state_elapsed := 0.0
var _queue: Array = []
var _dropped_count := 0
var _unsynced := false
var _last_close_code := 0
var _adapter := ProtocolAdapter.new()


func setup(
	url: String,
	handshake_timeout: float = DEFAULT_HANDSHAKE_TIMEOUT,
	queue_max: int = DEFAULT_QUEUE_MAX
) -> void:
	_url = url
	_handshake_timeout = handshake_timeout
	_queue_max = queue_max


func get_state() -> String:
	return _state


func is_open() -> bool:
	return _state == ConnectionState.CONNECTED


func last_close_code() -> int:
	return _last_close_code


func pending_count() -> int:
	return _queue.size()


func dropped_count() -> int:
	return _dropped_count


func has_unsynced() -> bool:
	return _unsynced


## 开始连接：创建 WebSocketPeer 并进入 CONNECTING（含握手超时计时）。
func connect_to_backend() -> void:
	if _state == ConnectionState.CONNECTED or _state == ConnectionState.CONNECTING:
		return
	if _url.is_empty():
		protocol_error.emit("INVALID_REQUEST", "backend websocket url is empty")
		return
	_peer = WebSocketPeer.new()
	_peer.inbound_buffer_size = ProtocolAdapter.MAX_MESSAGE_BYTES
	_peer.outbound_buffer_size = ProtocolAdapter.MAX_MESSAGE_BYTES
	begin_handshake()
	var err := _peer.connect_to_url(_url)
	if err != OK:
		_peer = null
		_handle_close(ConnectionState.CLOSE_SERVER_ERROR, "connect_to_url failed: %d" % err)


## 仅进入 CONNECTING 状态，不创建 peer；供握手超时等测试使用。
func begin_handshake() -> void:
	if _set_state(ConnectionState.CONNECTING):
		_state_elapsed = 0.0


func poll(delta: float) -> void:
	if (
		_state != ConnectionState.CONNECTING
		and _state != ConnectionState.CONNECTED
		and _state != ConnectionState.CLOSING
	):
		return

	_state_elapsed += delta
	if _state == ConnectionState.CONNECTING and _state_elapsed >= _handshake_timeout:
		_handle_close(ConnectionState.CLOSE_HANDSHAKE_TIMEOUT, "handshake timeout")
		return
	if _state == ConnectionState.CLOSING and _state_elapsed >= CLOSING_TIMEOUT:
		_handle_close(ConnectionState.CLOSE_NORMAL, "close timeout")
		return
	if _peer == null:
		return

	_peer.poll()
	var peer_state := _peer.get_ready_state()
	if peer_state == WebSocketPeer.STATE_OPEN:
		if _state == ConnectionState.CONNECTING:
			_set_state(ConnectionState.CONNECTED)
			_flush_queue()
		_read_packets()
	elif peer_state == WebSocketPeer.STATE_CLOSED:
		var code := _peer.get_close_code()
		var reason := _peer.get_close_reason()
		if code == 0:
			code = ConnectionState.CLOSE_SERVER_ERROR
		_handle_close(code, reason)


## 已连接时直接发送；否则入队。返回是否完成发送或入队。
func send_frame(frame: Dictionary, delivery: String = DELIVERY_PERSISTENT) -> bool:
	if (
		_state == ConnectionState.CONNECTED
		and _peer != null
		and _peer.get_ready_state() == WebSocketPeer.STATE_OPEN
	):
		return _write_frame(frame)
	return _enqueue(frame, delivery)


func close(code: int = 1000, reason: String = "") -> void:
	if _state == ConnectionState.DISCONNECTED or _state == ConnectionState.CONNECTION_LOST:
		return
	if _peer == null:
		_handle_close(code, reason)
		return
	_set_state(ConnectionState.CLOSING)
	_peer.close(code, reason)


func _read_packets() -> void:
	var processed := 0
	while (
		_peer != null
		and _peer.get_available_packet_count() > 0
		and processed < MAX_PACKETS_PER_POLL
	):
		var bytes := _peer.get_packet()
		processed += 1
		var result := _adapter.decode_text(bytes.get_string_from_utf8())
		if not bool(result.get("ok", false)):
			protocol_error.emit(str(result["error_code"]), str(result["error_message"]))
			var close_code := int(result.get("close_code", 0))
			if close_code != 0:
				_handle_close(close_code, str(result["error_message"]))
				return
			continue
		frame_received.emit(str(result["kind"]), result["frame"])


func _write_frame(frame: Dictionary) -> bool:
	if _peer == null:
		return false
	var encoded := _adapter.encode_frame(frame)
	if not bool(encoded.get("ok", false)):
		protocol_error.emit(str(encoded["error_code"]), str(encoded["error_message"]))
		var close_code := int(encoded.get("close_code", 0))
		if close_code != 0:
			_handle_close(close_code, str(encoded["error_message"]))
		return false
	var err := _peer.send_text(str(encoded["text"]))
	if err != OK:
		protocol_error.emit("INFRASTRUCTURE_ERROR", "send_text failed: %d" % err)
		return false
	return true


func _enqueue(frame: Dictionary, delivery: String) -> bool:
	if _queue.size() >= _queue_max:
		if delivery == DELIVERY_EPHEMERAL:
			_dropped_count += 1
			return false
		var removed := false
		for index in _queue.size():
			if str(_queue[index]["delivery"]) == DELIVERY_EPHEMERAL:
				_queue.remove_at(index)
				_dropped_count += 1
				removed = true
				break
		if not removed:
			_mark_unsynced()
			_dropped_count += 1
			return false
	_queue.append({
		"frame": frame,
		"delivery": delivery,
		"unsynced": false,
	})
	return true


func _mark_unsynced() -> void:
	_unsynced = true
	for entry in _queue:
		if str(entry["delivery"]) == DELIVERY_PERSISTENT:
			entry["unsynced"] = true


func _flush_queue() -> void:
	while not _queue.is_empty():
		var entry: Dictionary = _queue[0]
		if not _write_frame(entry["frame"]):
			return
		_queue.remove_at(0)


func _handle_close(code: int, reason: String) -> void:
	_last_close_code = code
	if _peer != null:
		if _peer.get_ready_state() == WebSocketPeer.STATE_OPEN:
			_peer.close(code, reason)
		_peer = null
	var reconnect := ConnectionState.should_reconnect(code)
	var target := ConnectionState.CONNECTION_LOST if reconnect else ConnectionState.DISCONNECTED
	if _state != target:
		_set_state(target)
	connection_closed.emit(code, reason, reconnect)


func _set_state(target: String) -> bool:
	if _state == target:
		return false
	if not ConnectionState.can_transition(_state, target):
		return false
	var previous := _state
	_state = target
	_state_elapsed = 0.0
	state_changed.emit(previous, target)
	return true
