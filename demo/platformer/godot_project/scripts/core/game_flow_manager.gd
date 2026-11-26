extends Node
## 游戏流程状态机（Autoload）。
##
## 权威状态只有本节点持有；UI 通过 "flow_ui" 组注册并按 ui_id 显示，
## 关卡由本节点负责加载与释放。

enum State { BOOT, MAIN_MENU, PLAYING, PAUSED, VICTORY, GAME_OVER, LEVEL_RESTART }

const LEVEL_SCENE := "res://scenes/levels/level_01.tscn"
const STATE_NAMES := {
	State.BOOT: "BOOT",
	State.MAIN_MENU: "MAIN_MENU",
	State.PLAYING: "PLAYING",
	State.PAUSED: "PAUSED",
	State.VICTORY: "VICTORY",
	State.GAME_OVER: "GAME_OVER",
	State.LEVEL_RESTART: "LEVEL_RESTART",
}

var state: int = State.BOOT
var level_root: Node2D = null
var current_level: Node = null
var last_score: int = 0


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS


func register_level_root(root: Node2D) -> void:
	level_root = root


func boot() -> void:
	_clear_level()
	get_tree().paused = false
	_set_state(State.MAIN_MENU)
	_show_ui("main_menu")


func start_game() -> void:
	if level_root == null:
		push_error("GameFlowManager: level_root 未注册")
		return
	_clear_level()
	var packed: PackedScene = load(LEVEL_SCENE)
	if packed == null:
		push_error("GameFlowManager: 无法加载关卡")
		return
	current_level = packed.instantiate()
	level_root.add_child(current_level)
	ScoreManager.reset_run()
	get_tree().paused = false
	_set_state(State.PLAYING)
	_show_ui("hud")
	EventBus.game_started.emit()


func restart_level() -> void:
	_set_state(State.LEVEL_RESTART)
	start_game()


func pause_game() -> void:
	if state != State.PLAYING:
		return
	get_tree().paused = true
	_set_state(State.PAUSED)
	_show_ui("pause_menu")
	EventBus.game_paused.emit()


func resume_game() -> void:
	if state != State.PAUSED:
		return
	get_tree().paused = false
	_set_state(State.PLAYING)
	_show_ui("hud")
	EventBus.game_resumed.emit()


func toggle_pause() -> void:
	if state == State.PLAYING:
		pause_game()
	elif state == State.PAUSED:
		resume_game()


func on_player_died() -> void:
	if state != State.PLAYING:
		return
	_set_state(State.GAME_OVER)
	_show_ui("result_screen")
	get_tree().paused = true
	last_score = ScoreManager.score
	EventBus.game_over.emit(last_score)
	EventBus.player_died.emit()


func on_goal_reached() -> void:
	if state != State.PLAYING:
		return
	last_score = ScoreManager.score
	var best := ScoreManager.commit_best()
	_set_state(State.VICTORY)
	_show_ui("result_screen")
	get_tree().paused = true
	EventBus.level_completed.emit(last_score)
	EventBus.best_score_changed.emit(best)


func to_menu() -> void:
	get_tree().paused = false
	boot()


func is_playing() -> bool:
	return state == State.PLAYING


func state_name() -> String:
	return STATE_NAMES.get(state, "UNKNOWN")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("pause"):
		toggle_pause()


func _clear_level() -> void:
	if current_level != null and is_instance_valid(current_level):
		level_root.remove_child(current_level)
		current_level.queue_free()
	current_level = null


func _set_state(next_state: int) -> void:
	if state == next_state:
		return
	state = next_state
	EventBus.game_state_changed.emit(state_name())


func _show_ui(ui_id: String) -> void:
	for node in get_tree().get_nodes_in_group("flow_ui"):
		if node.has_method("set_active"):
			node.call("set_active", node.get("ui_id") == ui_id)
