@tool
extends "res://tests/test_case.gd"
## E3-T01 生命周期单元测试（T01-UT-001…005）。

const PluginLifecycle := preload("res://addons/godot_ai_agent/core/plugin_lifecycle.gd")
const FakeService := preload("res://tests/e3/fakes/fake_service.gd")


class FakeHost extends RefCounted:
	var docks: Array = []
	var removed: Array = []

	func add_control_to_dock(_slot: int, control: Control) -> void:
		docks.append(control)

	func remove_control_from_docks(control: Control) -> void:
		docks.erase(control)
		removed.append(control)

	func get_editor_interface() -> Object:
		return null


func _init() -> void:
	suite_name = "t01_lifecycle"


## T01-UT-001：插件启用。
func test_enable() -> void:
	var lifecycle = PluginLifecycle.new()
	var service = FakeService.new()
	assert_true(lifecycle.add_service("alpha", service))
	var host := FakeHost.new()

	assert_true(lifecycle.enable(host, 3, "0.1.0"))
	assert_eq(lifecycle.get_state(), "READY")
	assert_eq(service.calls, ["initialize", "start"])
	assert_eq(host.docks.size(), 1)
	assert_not_null(service.context)
	assert_eq(service.context.get_config("backend_url"), "http://127.0.0.1:8765")
	assert_eq(str(lifecycle.status().get("state")), "READY")

	lifecycle.disable("test_done")


## T01-UT-002：插件关闭。
func test_disable() -> void:
	var lifecycle = PluginLifecycle.new()
	var service = FakeService.new()
	lifecycle.add_service("alpha", service)
	var host := FakeHost.new()
	lifecycle.enable(host, 3, "0.1.0")

	lifecycle.disable("test_shutdown")
	assert_eq(lifecycle.get_state(), "DISABLED")
	assert_eq(service.calls, ["initialize", "start", "stop:test_shutdown", "dispose"])
	assert_eq(host.docks.size(), 0)
	assert_eq(host.removed.size(), 1)
	assert_null(lifecycle.get_context())


## T01-UT-003：重复启用。
func test_duplicate_enable() -> void:
	var lifecycle = PluginLifecycle.new()
	var service = FakeService.new()
	lifecycle.add_service("alpha", service)
	var host := FakeHost.new()

	assert_true(lifecycle.enable(host, 3, "0.1.0"))
	assert_false(lifecycle.enable(host, 3, "0.1.0"))
	assert_eq(service.calls, ["initialize", "start"])
	assert_eq(host.docks.size(), 1)

	lifecycle.disable("first_close")
	assert_eq(host.docks.size(), 0)

	assert_true(lifecycle.enable(host, 3, "0.1.0"))
	assert_eq(service.calls, [
		"initialize", "start", "stop:first_close", "dispose", "initialize", "start",
	])
	assert_eq(host.docks.size(), 1)
	lifecycle.disable("second_close")


## T01-UT-004：初始化异常。
func test_initialization_failure() -> void:
	var lifecycle = PluginLifecycle.new()
	var service = FakeService.new()
	service.fail_start = true
	lifecycle.add_service("alpha", service)
	var host := FakeHost.new()

	assert_false(lifecycle.enable(host, 3, "0.1.0"))
	assert_eq(lifecycle.get_state(), "ERROR")
	assert_eq(str(lifecycle.status().get("error_code")), "SERVICE_START_FAILED")
	assert_eq(host.docks.size(), 1)

	# ERROR 状态下拒绝重复启用
	assert_false(lifecycle.enable(host, 3, "0.1.0"))

	lifecycle.disable("cleanup")
	assert_eq(lifecycle.get_state(), "DISABLED")
	assert_eq(host.docks.size(), 0)
	assert_eq(service.calls, ["initialize", "start", "stop:cleanup", "dispose"])


## T01-UT-005：关闭资源释放（逆序停止、Dock 释放、上下文清空）。
func test_disable_releases_resources() -> void:
	var lifecycle = PluginLifecycle.new()
	var trace: Array = []
	var alpha = FakeService.new()
	alpha.trace = trace
	var beta = FakeService.new()
	beta.trace = trace
	lifecycle.add_service("alpha", alpha)
	lifecycle.add_service("beta", beta, ["alpha"])
	var host := FakeHost.new()

	assert_true(lifecycle.enable(host, 3, "0.1.0"))
	assert_eq(trace, [
		"alpha:initialize", "alpha:start", "beta:initialize", "beta:start",
	])

	lifecycle.disable("shutdown")
	assert_eq(trace, [
		"alpha:initialize", "alpha:start", "beta:initialize", "beta:start",
		"beta:stop:shutdown", "beta:dispose",
		"alpha:stop:shutdown", "alpha:dispose",
	])
	assert_eq(host.docks.size(), 0)
	assert_null(alpha.context)
	assert_null(beta.context)
	assert_null(lifecycle.get_context())
