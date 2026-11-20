@tool
extends RefCounted
## 插件内部服务契约基类（E3-T02）。
##
## 所有插件服务必须继承本类，并实现受保护的钩子方法。
## 状态由基类统一维护，服务不得自行改写状态，避免注册表与 UI 读到不一致的值。


const STATE_CREATED := "CREATED"
const STATE_INITIALIZED := "INITIALIZED"
const STATE_RUNNING := "RUNNING"
const STATE_STOPPED := "STOPPED"
const STATE_FAILED := "FAILED"
const STATE_BLOCKED := "BLOCKED"


var service_name := ""
var context: Object = null

var _state := STATE_CREATED
var _error_code := ""
var _detail := ""


func initialize(plugin_context: Object) -> bool:
	if _state != STATE_CREATED and _state != STATE_STOPPED:
		fail("SERVICE_STATE_INVALID", "服务状态 %s 不允许初始化" % _state)
		return false
	_error_code = ""
	_detail = ""
	context = plugin_context
	var ok := _initialize()
	if not ok:
		if _error_code.is_empty():
			fail("SERVICE_INITIALIZE_FAILED", "服务初始化失败")
		_state = STATE_FAILED
		return false
	_state = STATE_INITIALIZED
	return true


func start() -> bool:
	if _state != STATE_INITIALIZED:
		fail("SERVICE_STATE_INVALID", "服务状态 %s 不允许启动" % _state)
		return false
	var ok := _start()
	if not ok:
		if _error_code.is_empty():
			fail("SERVICE_START_FAILED", "服务启动失败")
		_state = STATE_FAILED
		return false
	_state = STATE_RUNNING
	return true


func tick(delta: float) -> void:
	if _state != STATE_RUNNING:
		return
	_tick(delta)


func stop(reason: String = "") -> void:
	if _state == STATE_CREATED or _state == STATE_STOPPED:
		return
	_stop(reason)
	_state = STATE_STOPPED


func dispose() -> void:
	if _state != STATE_CREATED and _state != STATE_STOPPED:
		_stop("dispose")
		_state = STATE_STOPPED
	_dispose()
	context = null


func status() -> Dictionary:
	return {
		"name": service_name,
		"state": _state,
		"error_code": _error_code,
		"detail": _detail,
	}


func get_state() -> String:
	return _state


func is_running() -> bool:
	return _state == STATE_RUNNING


## 记录失败原因，由钩子方法在返回 false 前调用。
func fail(error_code: String, detail: String = "") -> void:
	_error_code = error_code
	_detail = detail


## 依赖未就绪时由注册表调用，服务不会再执行 initialize/start。
func mark_blocked(error_code: String, detail: String = "") -> void:
	_error_code = error_code
	_detail = detail
	_state = STATE_BLOCKED


# --- 子类钩子：默认无操作，仅需覆盖实际使用的方法 ---


func _initialize() -> bool:
	return true


func _start() -> bool:
	return true


func _tick(_delta: float) -> void:
	pass


func _stop(_reason: String) -> void:
	pass


func _dispose() -> void:
	pass
