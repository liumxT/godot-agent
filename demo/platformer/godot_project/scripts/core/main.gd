extends Node
## 主场景装配：注册关卡容器并进入主菜单。
##
## 传入 `-- --smoke` 时执行 headless 冒烟检查（CI 与验收使用），
## 不依赖真实输入，直接验证关卡生成与核心状态机。

func _ready() -> void:
	GameFlowManager.register_level_root($World)
	GameFlowManager.boot()
	if "--smoke" in OS.get_cmdline_user_args():
		_run_smoke_check()


func _run_smoke_check() -> void:
	await get_tree().process_frame
	GameFlowManager.start_game()
	await get_tree().create_timer(0.8).timeout

	var player = get_tree().get_first_node_in_group("player")
	var enemies := get_tree().get_nodes_in_group("enemy")
	var collectibles := get_tree().get_nodes_in_group("collectible")
	var hazards := get_tree().get_nodes_in_group("hazard")
	var goal := get_tree().get_first_node_in_group("goal")

	var checks: Array[bool] = [
		player != null,
		player != null and player.is_on_floor(),
		enemies.size() == 2,
		collectibles.size() == 15,
		hazards.size() == 2,
		goal != null,
		GameFlowManager.state_name() == "PLAYING",
	]
	if player != null:
		var before: int = player.health.current_health
		player.take_damage(1, Vector2.ZERO)
		checks.append(player.health.current_health == before - 1)
		checks.append(player.health.is_invulnerable())
		var during: int = player.health.current_health
		player.take_damage(1, Vector2.ZERO)
		checks.append(player.health.current_health == during)

	ScoreManager.reset_run()
	ScoreManager.add_score(10)
	checks.append(ScoreManager.score == 10)

	GameFlowManager.pause_game()
	checks.append(get_tree().paused)
	GameFlowManager.resume_game()
	checks.append(not get_tree().paused)

	var ok := not checks.has(false)
	print(
		"[SMOKE] player=%s enemies=%d collectibles=%d hazards=%d goal=%s checks=%d"
		% [
			str(player != null),
			enemies.size(),
			collectibles.size(),
			hazards.size(),
			str(goal != null),
			checks.size(),
		]
	)
	print("[SMOKE] RESULT=%s" % ("PASS" if ok else "FAIL"))
	get_tree().quit(0 if ok else 1)
