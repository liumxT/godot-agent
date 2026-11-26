extends Node
## 分数权威来源：只有本节点可以修改当前分数。

var score: int = 0
var best_score: int = 0


func _ready() -> void:
	best_score = SaveManager.get_best_score()


func reset_run() -> void:
	score = 0
	EventBus.score_changed.emit(score)


func add_score(value: int) -> void:
	if value <= 0:
		return
	score += value
	EventBus.score_changed.emit(score)


func commit_best() -> int:
	if score > best_score:
		best_score = SaveManager.submit_best_score(score)
	return best_score
