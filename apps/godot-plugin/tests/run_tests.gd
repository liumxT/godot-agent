extends SceneTree
## E3 Godot 侧测试入口（SceneTree 版本）。
##
## 用法：
##   godot --headless --path apps/godot-plugin --script res://tests/run_tests.gd
##
## 若当前 Godot 构建的 --script 不可用，可使用编辑器模式入口：
##   godot --headless --path apps/godot-plugin --editor --quit-after 600 -- --e3-test


const TestRunner := preload("res://tests/test_runner.gd")


func _initialize() -> void:
	var result: Dictionary = TestRunner.new().run_all()
	var ok := int(result.get("failed", 1)) == 0 and int(result.get("total", 0)) > 0
	quit(0 if ok else 1)
