extends RefCounted
## E3 Godot 侧测试执行器（不依赖 GUT）。
##
## 发现并执行 `tests/e3/test_*.gd` 中无参的 `test_` 方法。
## 供两种入口复用：
##   - tests/run_tests.gd（SceneTree，--script 可用时）
##   - tests/e3_runner/plugin.gd（EditorPlugin，编辑器模式/CI）


const TEST_DIR := "res://tests/e3"


func run_all() -> Dictionary:
	var files := _discover()
	var total := 0
	var failed := 0

	for path in files:
		var script: Script = load(path)
		if script == null:
			printerr("[FAIL] 无法加载测试脚本: %s" % path)
			failed += 1
			continue

		var suite: Object = script.new()
		var suite_name := str(suite.get("suite_name"))
		if suite_name.is_empty():
			suite_name = path.get_file().get_basename()

		for method in suite.get_method_list():
			var method_name := str(method.get("name", ""))
			if not method_name.begins_with("test_"):
				continue
			if not method.get("args", []).is_empty():
				continue

			total += 1
			suite.call("reset")
			suite.call(method_name)

			var failures: Array = suite.get("failures")
			if failures.is_empty():
				print("[PASS] %s::%s" % [suite_name, method_name])
			else:
				failed += 1
				printerr("[FAIL] %s::%s" % [suite_name, method_name])
				for message in failures:
					printerr("  - %s" % str(message))

	print("godot tests: %d/%d passed" % [total - failed, total])
	return {"total": total, "failed": failed}


func _discover() -> Array:
	var files: Array = []
	var dir := DirAccess.open(TEST_DIR)
	if dir == null:
		printerr("[FAIL] 无法打开测试目录: %s" % TEST_DIR)
		return files
	for file_name in dir.get_files():
		if file_name.begins_with("test_") and file_name.ends_with(".gd"):
			files.append(TEST_DIR.path_join(file_name))
	files.sort()
	return files
