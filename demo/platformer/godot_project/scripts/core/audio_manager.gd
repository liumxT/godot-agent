extends Node
## 音频管理：统一加载占位音效，并订阅事件总线。

var _jump: AudioStreamPlayer
var _hurt: AudioStreamPlayer
var _collect: AudioStreamPlayer
var _bgm: AudioStreamPlayer


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_jump = _make("res://assets/audio/jump.wav", -6.0)
	_hurt = _make("res://assets/audio/hurt.wav", -4.0)
	_collect = _make("res://assets/audio/collect.wav", -6.0)
	_bgm = _make("res://assets/audio/bgm.wav", -18.0, true)
	EventBus.player_jumped.connect(_on_jump)
	EventBus.player_damaged.connect(_on_hurt)
	EventBus.collectible_collected.connect(_on_collect)
	EventBus.game_started.connect(_on_game_started)
	EventBus.game_over.connect(_on_game_stopped)
	EventBus.level_completed.connect(_on_game_stopped)


func _make(path: String, volume_db: float, loop: bool = false) -> AudioStreamPlayer:
	var player := AudioStreamPlayer.new()
	var stream: AudioStream = load(path)
	if loop and stream is AudioStreamWAV:
		stream.loop_mode = AudioStreamWAV.LOOP_FORWARD
		stream.loop_end = int(stream.get_length() * stream.mix_rate)
	player.stream = stream
	player.volume_db = volume_db
	add_child(player)
	return player


func _on_jump() -> void:
	_play(_jump)


func _on_hurt(_amount: int) -> void:
	_play(_hurt)


func _on_collect(_value: int) -> void:
	_play(_collect)


func _on_game_started() -> void:
	if _bgm != null and not _bgm.playing:
		_bgm.play()


func _on_game_stopped(_score: int = 0) -> void:
	if _bgm != null:
		_bgm.stop()


func _play(player: AudioStreamPlayer) -> void:
	if player != null and player.stream != null:
		player.play()
