extends Node
## 本地存档：JSON 文件位于 user://，损坏时回退安全默认值。

const SAVE_PATH := "user://platformer_save.json"
const DEFAULT_BEST := 0

var last_load_error: String = ""


func get_best_score() -> int:
	return int(_load().get("best_score", DEFAULT_BEST))


func submit_best_score(value: int) -> int:
	var best := maxi(value, get_best_score())
	_store({"best_score": best, "version": 1})
	return best


func _load() -> Dictionary:
	if not FileAccess.file_exists(SAVE_PATH):
		return {"best_score": DEFAULT_BEST}
	var text := FileAccess.get_file_as_string(SAVE_PATH)
	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		last_load_error = "存档内容不是对象，已回退默认值"
		push_warning("SaveManager: " + last_load_error)
		return {"best_score": DEFAULT_BEST}
	var best := int(parsed.get("best_score", DEFAULT_BEST))
	if best < 0:
		last_load_error = "最佳分数为负数，已回退默认值"
		push_warning("SaveManager: " + last_load_error)
		best = DEFAULT_BEST
	return {"best_score": best}


func _store(payload: Dictionary) -> void:
	var file := FileAccess.open(SAVE_PATH, FileAccess.WRITE)
	if file == null:
		push_warning("SaveManager: 无法写入存档")
		return
	file.store_string(JSON.stringify(payload))
	file.close()
