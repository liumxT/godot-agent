@tool
extends EditorPlugin
## 契约样例校验探针（仅测试用，不属于产品插件）。
##
## 运行：
##   godot --headless --editor --path apps/godot-plugin --quit-after 600 -- --contract-test
##
## 与 Backend 的 tests/contract/test_protocol_samples.py 读取同一份 manifest。

const FLAG := "--contract-test"
const Validator := preload("res://addons/godot_ai_agent/core/contract_validator.gd")


func _enter_tree() -> void:
	if not OS.get_cmdline_user_args().has(FLAG):
		return
	call_deferred("_run_tests")


func _run_tests() -> void:
	var contracts_root := ProjectSettings.globalize_path("res://") \
		.path_join("../../packages/contracts").simplify_path()
	var manifest := _read_json(contracts_root.path_join("schemas/manifest.json"))
	if manifest.is_empty():
		printerr("[FAIL] cannot read manifest under %s" % contracts_root)
		get_tree().quit(1)
		return

	var total := 0
	var failures := 0
	for item in manifest.get("cases", []):
		total += 1
		var case_path := contracts_root.path_join("schemas").path_join(str(item["file"]))
		var sample = _read_json(case_path)
		var errors: Array = _validate(str(item["schema"]), sample)
		var actual_valid: bool = errors.is_empty()
		var expected_valid: bool = bool(item["valid"])
		if actual_valid != expected_valid:
			failures += 1
			printerr("[FAIL] %s expected valid=%s, got errors=%s" % [
				item["id"], expected_valid, errors
			])
		else:
			print("[PASS] %s" % item["id"])

	print("contract samples: %d/%d passed" % [total - failures, total])
	get_tree().quit(1 if failures > 0 else 0)


func _validate(schema: String, sample: Variant) -> Array:
	match schema:
		"api/request.schema.json":
			return Validator.validate_request(sample)
		"api/response.schema.json":
			return Validator.validate_response(sample)
		"events/event.schema.json":
			return Validator.validate_event(sample)
		"errors/error.schema.json":
			return Validator.validate_error(sample)
		"api/system.schema.json":
			return Validator.validate_system(sample)
		"api/client.schema.json":
			return Validator.validate_client(sample)
		"api/auth.schema.json":
			return Validator.validate_auth(sample)
		"api/session.schema.json":
			return Validator.validate_session(sample)
		"api/project-access.schema.json":
			return Validator.validate_project_access(sample)
		"bridge/control.schema.json":
			return Validator.validate_bridge_control(sample)
		"bridge/session-created.schema.json":
			return Validator.validate_bridge_session_created(sample)
		"bridge/lease.schema.json":
			return Validator.validate_bridge_lease(sample)
		"bridge/session-binding.schema.json":
			return Validator.validate_bridge_session_binding(sample)
		"bridge/editor-state.schema.json":
			return Validator.validate_bridge_editor_state(sample)
		"bridge/snapshot.schema.json":
			return Validator.validate_bridge_snapshot(sample)
		"bridge/runtime.schema.json":
			return Validator.validate_bridge_runtime(sample)
		_:
			return ["unknown schema: %s" % schema]


func _read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		printerr("[FAIL] file not found: %s" % path)
		return {}
	var text := FileAccess.get_file_as_string(path)
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		printerr("[FAIL] invalid json: %s" % path)
		return {}
	return parsed
