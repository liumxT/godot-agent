extends Node
## 全局事件总线：只承载跨系统信号，不持有状态。

signal game_started
signal game_state_changed(state_name: String)
signal score_changed(score: int)
signal best_score_changed(best_score: int)
signal health_changed(current: int, maximum: int)
signal player_damaged(amount: int)
signal player_jumped
signal player_died
signal collectible_collected(value: int)
signal enemy_defeated
signal level_completed(final_score: int)
signal game_over(final_score: int)
signal game_paused
signal game_resumed
