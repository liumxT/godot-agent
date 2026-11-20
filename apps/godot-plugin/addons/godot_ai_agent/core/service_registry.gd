@tool
extends RefCounted
## 插件服务注册表（E3-T02）。
##
## 负责服务注册、依赖拓扑排序、批量启动/停止、逐帧调度与状态快照。
## 不直接处理网络、UI 或编辑器对象，只与 `service.gd` 契约交互。


const PluginLog := preload("res://addons/godot_ai_agent/core/logger.gd")
const ServiceBase := preload("res://addons/godot_ai_agent/core/service.gd")


var _context: Object = null
var _entries: Dictionary = {}
var _registration_order: Array = []
var _start_order: Array = []


func _init(context: Object = null) -> void:
	_context = context


## 注册服务。依赖可以后注册，但在 start_all() 前必须存在。
func register(name: String, service: Object, dependencies: Array = []) -> bool:
	if name.is_empty():
		PluginLog.error("service_register_invalid", {"reason": "empty_name"})
		return false
	if service == null or not (service is ServiceBase):
		PluginLog.error("service_register_invalid", {
			"service": name,
			"reason": "service 必须继承 core/service.gd",
		})
		return false
	if _entries.has(name):
		PluginLog.warn("service_register_duplicate", {"service": name})
		return false

	var deps: Array = []
	for dependency in dependencies:
		var dep_name := str(dependency)
		if dep_name.is_empty() or dep_name == name:
			PluginLog.error("service_register_invalid", {
				"service": name,
				"reason": "非法依赖：%s" % dep_name,
			})
			return false
		if not deps.has(dep_name):
			deps.append(dep_name)

	service.set("service_name", name)
	_entries[name] = {"service": service, "dependencies": deps}
	_registration_order.append(name)
	return true


## 按名取服务。GDScript 不允许重载 Object.get()，因此命名为 get_service。
func get_service(name: String) -> Object:
	if not _entries.has(name):
		return null
	return _entries[name]["service"]


## 按拓扑序初始化并启动全部服务；任一失败时其依赖方标记为 BLOCKED。
func start_all() -> bool:
	if _entries.is_empty():
		return true

	var order := _resolve_order()
	if order.is_empty():
		_mark_all("DEPENDENCY_INVALID", "服务依赖无效或存在循环依赖")
		return false

	var started: Array = []
	var all_running := true
	for name in order:
		var entry: Dictionary = _entries[name]
		var service: Object = entry["service"]

		var missing: Array = []
		for dep in entry["dependencies"]:
			var dep_service: Object = _entries[dep]["service"]
			var dep_status: Dictionary = dep_service.call("status")
			if str(dep_status.get("state", "")) != ServiceBase.STATE_RUNNING:
				missing.append(str(dep))
		if not missing.is_empty():
			service.call("mark_blocked", "DEPENDENCY_BLOCKED", "依赖服务未就绪: %s" % ", ".join(missing))
			all_running = false
			continue

		if not bool(service.call("initialize", _context)):
			all_running = false
			continue
		if not bool(service.call("start")):
			all_running = false
			continue
		started.append(name)

	_start_order = started
	return all_running


## 按启动逆序停止并释放全部服务，随后清空注册表。
func stop_all(reason: String = "shutdown") -> void:
	var order := _resolve_order()
	if order.is_empty():
		order = _registration_order.duplicate()
	order.reverse()

	for name in order:
		if not _entries.has(name):
			continue
		var service: Object = _entries[name]["service"]
		service.call("stop", reason)
		service.call("dispose")

	_entries.clear()
	_registration_order.clear()
	_start_order.clear()


## 注销单个服务；仍被其他服务依赖时拒绝。
func unregister(name: String) -> bool:
	if not _entries.has(name):
		return false
	for other in _entries:
		if other == name:
			continue
		if _entries[other]["dependencies"].has(name):
			PluginLog.warn("service_unregister_in_use", {
				"service": name,
				"dependent": str(other),
			})
			return false

	var service: Object = _entries[name]["service"]
	service.call("stop", "unregistered")
	service.call("dispose")
	_start_order.erase(name)
	_registration_order.erase(name)
	_entries.erase(name)
	return true


## 仅调度处于 RUNNING 的服务。
func tick(delta: float) -> void:
	for name in _start_order:
		if not _entries.has(name):
			continue
		var service: Object = _entries[name]["service"]
		service.call("tick", delta)


func snapshot() -> Dictionary:
	var services := {}
	for name in _registration_order:
		var entry: Dictionary = _entries[name]
		var service: Object = entry["service"]
		var service_status: Dictionary = service.call("status")
		services[name] = {
			"state": str(service_status.get("state", "")),
			"error_code": str(service_status.get("error_code", "")),
			"detail": str(service_status.get("detail", "")),
			"dependencies": entry["dependencies"].duplicate(),
		}
	return {
		"order": _registration_order.duplicate(),
		"services": services,
	}


func is_empty() -> bool:
	return _entries.is_empty()


## Kahn 拓扑排序，保持注册顺序作为稳定次序。
func _resolve_order() -> Array:
	var indegree := {}
	var dependents := {}
	for name in _registration_order:
		indegree[name] = 0
		dependents[name] = []

	for name in _registration_order:
		for dep in _entries[name]["dependencies"]:
			if not _entries.has(dep):
				PluginLog.error("service_dependency_missing", {
					"service": str(name),
					"dependency": str(dep),
				})
				return []
			indegree[name] = int(indegree[name]) + 1
			dependents[dep].append(name)

	var queue: Array = []
	for name in _registration_order:
		if int(indegree[name]) == 0:
			queue.append(name)

	var order: Array = []
	while not queue.is_empty():
		var current: String = queue.pop_front()
		order.append(current)
		for dependent in dependents[current]:
			indegree[dependent] = int(indegree[dependent]) - 1
			if int(indegree[dependent]) == 0:
				queue.append(dependent)

	if order.size() != _registration_order.size():
		PluginLog.error("service_dependency_cycle", {"order": str(order)})
		return []
	return order


func _mark_all(error_code: String, detail: String) -> void:
	for name in _registration_order:
		var service: Object = _entries[name]["service"]
		service.call("mark_blocked", error_code, detail)
