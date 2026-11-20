@tool
extends EditorPlugin
## E3 单元测试的编辑器模式入口（仅测试用）。
##
## 运行：
##   godot --headless --path apps/godot-plugin --editor --quit-after 600 -- --e3-test
##
## 无该参数时完全不执行任何逻辑。


const FLAG := "--e3-test"
const TestRunner := preload("res://tests/test_runner.gd")


func _enter_tree() -> void:
	if not OS.get_cmdline_user_args().has(FLAG):
		return
	call_deferred("_run")


func _run() -> void:
	var result: Dictionary = TestRunner.new().run_all()
	var ok := int(result.get("failed", 1)) == 0 and int(result.get("total", 0)) > 0
	get_tree().quit(0 if ok else 1)
