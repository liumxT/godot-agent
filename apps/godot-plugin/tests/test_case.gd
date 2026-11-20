extends RefCounted
## 轻量断言基类（E3-M1）。
##
## 测试脚本继承本类，提供 `test_` 前缀的无参方法；run_tests.gd 负责发现与执行。


var suite_name := ""
var failures: Array[String] = []
var assertion_count := 0


func reset() -> void:
	failures.clear()
	assertion_count = 0


func assert_true(condition: bool, message: String = "") -> void:
	assertion_count += 1
	if not condition:
		failures.append(_format(message, "期望为 true"))


func assert_false(condition: bool, message: String = "") -> void:
	assertion_count += 1
	if condition:
		failures.append(_format(message, "期望为 false"))


func assert_eq(actual: Variant, expected: Variant, message: String = "") -> void:
	assertion_count += 1
	if actual != expected:
		failures.append(_format(message, "期望 %s，实际 %s" % [str(expected), str(actual)]))


func assert_null(value: Variant, message: String = "") -> void:
	assertion_count += 1
	if value != null:
		failures.append(_format(message, "期望为 null，实际 %s" % str(value)))


func assert_not_null(value: Variant, message: String = "") -> void:
	assertion_count += 1
	if value == null:
		failures.append(_format(message, "期望非 null"))


func _format(message: String, detail: String) -> String:
	if message.is_empty():
		return detail
	return "%s（%s）" % [message, detail]
