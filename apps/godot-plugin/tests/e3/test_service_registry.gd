@tool
extends "res://tests/test_case.gd"
## E3-T02 服务注册表单元测试（T02-UT-001…003）。

const ServiceRegistry := preload("res://addons/godot_ai_agent/core/service_registry.gd")
const FakeService := preload("res://tests/e3/fakes/fake_service.gd")


func _init() -> void:
	suite_name = "t02_service_registry"


## T02-UT-001：依赖拓扑顺序启动（注册顺序与依赖顺序相反）。
func test_topological_start_order() -> void:
	var registry = ServiceRegistry.new(null)
	var trace: Array = []
	var alpha = FakeService.new()
	alpha.trace = trace
	var beta = FakeService.new()
	beta.trace = trace
	var gamma = FakeService.new()
	gamma.trace = trace

	assert_true(registry.register("gamma", gamma, ["beta"]))
	assert_true(registry.register("beta", beta, ["alpha"]))
	assert_true(registry.register("alpha", alpha, []))
	assert_true(registry.start_all())

	assert_eq(trace, [
		"alpha:initialize", "alpha:start",
		"beta:initialize", "beta:start",
		"gamma:initialize", "gamma:start",
	])
	assert_eq(alpha.get_state(), "RUNNING")
	assert_eq(gamma.get_state(), "RUNNING")


## T02-UT-002：依赖失败时依赖方标记 BLOCKED。
func test_dependency_failure_blocks_dependents() -> void:
	var registry = ServiceRegistry.new(null)
	var alpha = FakeService.new()
	alpha.fail_start = true
	var beta = FakeService.new()
	var gamma = FakeService.new()

	registry.register("alpha", alpha, [])
	registry.register("beta", beta, ["alpha"])
	registry.register("gamma", gamma, ["beta"])

	assert_false(registry.start_all())
	assert_eq(alpha.get_state(), "FAILED")
	assert_eq(beta.get_state(), "BLOCKED")
	assert_eq(gamma.get_state(), "BLOCKED")

	var snapshot: Dictionary = registry.snapshot()
	assert_eq(snapshot["services"]["beta"]["error_code"], "DEPENDENCY_BLOCKED")
	assert_eq(snapshot["services"]["gamma"]["error_code"], "DEPENDENCY_BLOCKED")


## T02-UT-003：重复注册拒绝、tick 仅调度运行中服务、停止按逆序。
func test_duplicate_register_tick_and_stop() -> void:
	var registry = ServiceRegistry.new(null)
	var trace: Array = []
	var alpha = FakeService.new()
	alpha.trace = trace
	var beta = FakeService.new()
	beta.trace = trace

	assert_true(registry.register("alpha", alpha, []))
	assert_false(registry.register("alpha", FakeService.new(), []))
	assert_true(registry.register("beta", beta, ["alpha"]))
	assert_false(registry.unregister("alpha"))

	assert_true(registry.start_all())
	registry.tick(0.016)
	assert_eq(alpha.calls, ["initialize", "start", "tick"])
	assert_eq(beta.calls, ["initialize", "start", "tick"])

	registry.stop_all("shutdown")
	assert_eq(trace, [
		"alpha:initialize", "alpha:start",
		"beta:initialize", "beta:start",
		"alpha:tick", "beta:tick",
		"beta:stop:shutdown", "beta:dispose",
		"alpha:stop:shutdown", "alpha:dispose",
	])
	assert_true(registry.is_empty())
	assert_null(registry.get_service("alpha"))
