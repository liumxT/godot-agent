@tool
extends EditorPlugin
## T01-IT-001 集成探针（仅测试用，不属于产品插件）。
##
## 运行：
##   godot --headless --path apps/godot-plugin --editor --quit-after 600 \
##     -- --lifecycle-test
##
## 通过 EditorInterface 反复禁用/启用主插件，校验插件实例与状态面板数量：
## 启用时应恰好 1 个插件实例与 1 个面板，关闭后应全部释放。


const FLAG := "--lifecycle-test"
const MAIN_SCRIPT := "res://addons/godot_ai_agent/plugin.gd"
const PANEL_SCRIPT := "res://addons/godot_ai_agent/ui/status_panel.gd"
const PLUGIN_ID_FRAGMENT := "godot_ai_agent"
const MAX_WAIT_FRAMES := 180


var _failures := 0


func _enter_tree() -> void:
	if not OS.get_cmdline_user_args().has(FLAG):
		return
	call_deferred("_run")


func _run() -> void:
	var plugin_id := _plugin_identifier()
	if plugin_id.is_empty():
		printerr("[FAIL] 无法定位主插件标识")
		get_tree().quit(1)
		return

	await _expect(1, "initial_enable")

	EditorInterface.set_plugin_enabled(plugin_id, false)
	await _expect(0, "after_disable")

	EditorInterface.set_plugin_enabled(plugin_id, true)
	await _expect(1, "after_reenable")

	EditorInterface.set_plugin_enabled(plugin_id, false)
	await _expect(0, "after_second_disable")

	EditorInterface.set_plugin_enabled(plugin_id, true)
	await _expect(1, "after_second_enable")

	print("lifecycle probe: %d failure(s)" % _failures)
	get_tree().quit(1 if _failures > 0 else 0)


func _expect(expected: int, label: String) -> void:
	for _frame in range(MAX_WAIT_FRAMES):
		await get_tree().process_frame
		if _count_script(MAIN_SCRIPT) == expected and _count_script(PANEL_SCRIPT) == expected:
			print("[PASS] %s" % label)
			return

	_failures += 1
	printerr("[FAIL] %s: plugins=%d panels=%d expected=%d" % [
		label,
		_count_script(MAIN_SCRIPT),
		_count_script(PANEL_SCRIPT),
		expected,
	])


func _count_script(path: String) -> int:
	var count := 0
	for node in get_tree().root.find_children("*", "", true, false):
		var script_value: Variant = node.get_script()
		if script_value != null and str(script_value.resource_path) == path:
			count += 1
	return count


func _plugin_identifier() -> String:
	var settings := EditorInterface.get_editor_settings()
	var entries: Variant = settings.get_setting("editor_plugins/enabled")
	if entries != null:
		for entry in entries:
			if str(entry).contains(PLUGIN_ID_FRAGMENT):
				return str(entry)
	return "res://addons/godot_ai_agent/plugin.cfg"
