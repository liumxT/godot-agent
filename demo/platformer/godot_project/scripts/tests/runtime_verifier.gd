extends Node
## 运行时功能验证：用真实输入与物理帧驱动关卡，输出可审计的 [VERIFY] 证据。
##
## 使用：
##   Godot --headless --path godot_project res://scenes/tests/runtime_verifier.tscn
## 覆盖：移动、跳跃、攻击命中与冷却、敌人巡逻与攻击、陷阱伤害、
##       无敌帧、收集计分、死亡与 Game Over、胜利结算、暂停与恢复。

const MAIN_SCENE := preload("res://scenes/main/main.tscn")

var _passed: int = 0
var _failed: int = 0


func _ready() -> void:
	await get_tree().process_frame
	var main = MAIN_SCENE.instantiate()
	add_child(main)
	await get_tree().process_frame
	await _verify()


func _check(case_id: String, ok: bool, detail: String = "") -> void:
	if ok:
		_passed += 1
	else:
		_failed += 1
	print("[VERIFY] CASE=%s RESULT=%s %s" % [case_id, "PASS" if ok else "FAIL", detail])


func _physics_frames(count: int) -> void:
	for _i in count:
		await get_tree().physics_frame


func _seconds(value: float) -> void:
	await get_tree().create_timer(value).timeout


func _player():
	return get_tree().get_first_node_in_group("player")


func _verify() -> void:
	GameFlowManager.start_game()
	await _physics_frames(12)

	var player = _player()
	_check("PLAYER_SPAWNED", player != null)
	if player == null:
		_finish()
		return
	_check("PLAYER_ON_GROUND", player.is_on_floor())

	# 生成数量（越早检查越不受后续玩法影响）
	_check("ENEMY_COUNT", get_tree().get_nodes_in_group("enemy").size() == 2)
	_check("COLLECTIBLE_COUNT", get_tree().get_nodes_in_group("collectible").size() == 15)
	_check("HAZARD_COUNT", get_tree().get_nodes_in_group("hazard").size() == 2)
	_check("GOAL_EXISTS", get_tree().get_first_node_in_group("goal") != null)

	# TC-003 左右移动
	var start_x: float = player.global_position.x
	Input.action_press("move_right")
	await _physics_frames(20)
	Input.action_release("move_right")
	await _physics_frames(4)
	var moved: float = player.global_position.x - start_x
	_check("MOVE_RIGHT", moved > 20.0, "dx=%.1f" % moved)

	# TC-004 跳跃
	await _physics_frames(10)
	var ground_y: float = player.global_position.y
	Input.action_press("jump")
	await _physics_frames(3)
	Input.action_release("jump")
	await _physics_frames(6)
	var rise: float = ground_y - player.global_position.y
	_check("JUMP", rise > 10.0 or player.velocity.y < 0.0, "rise=%.1f" % rise)
	await _physics_frames(70)

	# TC-005 / TC-006 攻击命中、单次攻击不重复扣血、冷却阻止连发
	var enemy = get_tree().get_nodes_in_group("enemy")[0]
	player.global_position = enemy.global_position + Vector2(-30.0, 0.0)
	player.velocity = Vector2.ZERO
	await _physics_frames(3)
	var enemy_hp: int = enemy.health
	Input.action_press("attack")
	await _physics_frames(2)
	Input.action_release("attack")
	await _physics_frames(2)
	_check("ATTACK_DAMAGES_ENEMY", enemy.health == enemy_hp - 1, "hp=%d" % enemy.health)
	_check("ATTACK_COOLDOWN_BLOCKS", not bool(player.combat.try_attack(1)))
	var enemy_hp_mid: int = enemy.health
	await _physics_frames(4)
	_check("ATTACK_NO_DOUBLE_HIT", enemy.health == enemy_hp_mid)
	await _physics_frames(16)

	# 二次攻击击杀敌人（验证生命归零与死亡流程）
	player.global_position = enemy.global_position + Vector2(-30.0, 0.0)
	player.velocity = Vector2.ZERO
	await _physics_frames(2)
	Input.action_press("attack")
	await _physics_frames(2)
	Input.action_release("attack")
	await _physics_frames(8)
	_check("ENEMY_DEFEATED", bool(enemy.dead) or not is_instance_valid(enemy))

	# TC-008 敌人巡逻（选一个仍存活的敌人，远离玩家）
	var patroller = null
	for candidate in get_tree().get_nodes_in_group("enemy"):
		if is_instance_valid(candidate) and not bool(candidate.get("dead")):
			patroller = candidate
			break
	player.global_position = Vector2(96.0, 296.0)
	player.velocity = Vector2.ZERO
	await _physics_frames(6)
	if patroller == null:
		_check("ENEMY_PATROL", false, "no living enemy")
	else:
		var patrol_start: float = patroller.global_position.x
		await _physics_frames(40)
		var patrol_delta: float = absf(patroller.global_position.x - patrol_start)
		_check("ENEMY_PATROL", patrol_delta > 4.0, "dx=%.1f" % patrol_delta)

	# TC-011 陷阱伤害 + 无敌帧
	var hazards := get_tree().get_nodes_in_group("hazard")
	var hp_before: int = player.health.current_health
	player.global_position = hazards[0].global_position + Vector2(0.0, -8.0)
	player.velocity = Vector2.ZERO
	await _physics_frames(4)
	_check("HAZARD_DAMAGE", player.health.current_health == hp_before - 1, "hp=%d" % player.health.current_health)
	_check("INVULNERABLE_AFTER_HIT", player.health.is_invulnerable())
	var hp_after: int = player.health.current_health
	player.global_position = hazards[1].global_position + Vector2(0.0, -8.0)
	await _physics_frames(4)
	_check("IFRAME_BLOCKS_REPEAT", player.health.current_health == hp_after)

	# TC-010 收集物与计分（等待无敌帧结束，避免状态干扰）
	await _seconds(1.2)
	var coin = null
	for candidate in get_tree().get_nodes_in_group("collectible"):
		if is_instance_valid(candidate) and not bool(candidate.get("collected")):
			coin = candidate
			break
	if coin == null:
		_check("COLLECT_ADDS_SCORE", false, "no collectible")
		_check("COLLECT_ONCE", false)
	else:
		var coin_value: int = int(coin.value)
		ScoreManager.reset_run()
		player.global_position = coin.global_position
		player.velocity = Vector2.ZERO
		await _physics_frames(5)
		_check("COLLECT_ADDS_SCORE", ScoreManager.score == coin_value, "score=%d" % ScoreManager.score)
		_check("COLLECT_ONCE", (not is_instance_valid(coin)) or bool(coin.collected))

	# TC-007 死亡与 Game Over
	for _i in 4:
		if player.is_dead():
			break
		player.take_damage(1, Vector2.ZERO)
		await _seconds(1.2)
	await _seconds(0.8)
	_check("PLAYER_DEAD", player.is_dead())
	_check("FLOW_GAME_OVER", GameFlowManager.state_name() == "GAME_OVER")

	# TC-014 胜利结算
	GameFlowManager.start_game()
	await _physics_frames(10)
	var victory_player = _player()
	var goal = get_tree().get_first_node_in_group("goal")
	if goal != null and victory_player != null:
		victory_player.global_position = goal.global_position + Vector2(0.0, -24.0)
		victory_player.velocity = Vector2.ZERO
		await _physics_frames(6)
	_check("FLOW_VICTORY", GameFlowManager.state_name() == "VICTORY")

	# TC-012 / TC-013 暂停与恢复
	GameFlowManager.start_game()
	await _physics_frames(8)
	GameFlowManager.pause_game()
	_check("PAUSE", get_tree().paused and GameFlowManager.state_name() == "PAUSED")
	GameFlowManager.resume_game()
	_check("RESUME", (not get_tree().paused) and GameFlowManager.state_name() == "PLAYING")

	# TC-009 敌人攻击命中玩家
	var attackers := get_tree().get_nodes_in_group("enemy")
	var live_player = _player()
	if attackers.size() > 0 and live_player != null:
		var attacker = attackers[0]
		live_player.global_position = attacker.global_position + Vector2(16.0, 0.0)
		live_player.velocity = Vector2.ZERO
		var hp_prior: int = live_player.health.current_health
		await _physics_frames(45)
		_check(
			"ENEMY_ATTACKS_PLAYER",
			live_player.health.current_health < hp_prior,
			"hp=%d" % live_player.health.current_health
		)
	else:
		_check("ENEMY_ATTACKS_PLAYER", false, "missing enemy or player")

	_finish()


func _finish() -> void:
	print("[VERIFY] SUMMARY passed=%d failed=%d" % [_passed, _failed])
	print("[VERIFY] RESULT=%s" % ("PASS" if _failed == 0 else "FAIL"))
	get_tree().quit(0 if _failed == 0 else 1)
