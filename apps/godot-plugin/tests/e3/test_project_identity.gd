@tool
extends "res://tests/test_case.gd"
## 项目身份测试（E3-T14 客户端侧）。

const ProjectIdentity := preload("res://addons/godot_ai_agent/state/project_identity.gd")


func _init() -> void:
	suite_name = "t14_project_identity"


## T14-UT-001：根目录与 project.godot 必须可读。
func test_identity_reports_valid_project() -> void:
	var identity := ProjectIdentity.new()
	assert_false(identity.root_path().is_empty())
	assert_true(identity.root_path().ends_with("/"))
	assert_true(identity.project_file_path().ends_with("project.godot"))
	assert_true(FileAccess.file_exists(identity.project_file_path()))
	assert_true(identity.is_valid())


## T14-UT-002：HELLO 项目字段只包含服务端需要的原始事实。
func test_identity_hello_payload() -> void:
	var identity := ProjectIdentity.new()
	var hello := identity.to_hello()
	assert_eq(
		hello.keys().size(),
		3,
		"项目字段集合固定",
	)
	assert_eq(str(hello["root"]), identity.root_path())
	assert_eq(str(hello["name"]), identity.project_name())
	assert_eq(str(hello["godot_version"]), identity.godot_version())
	assert_true(not str(hello["name"]).is_empty())
	assert_true(str(hello["godot_version"]).begins_with("4."))
