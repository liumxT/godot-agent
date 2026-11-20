@tool
extends RefCounted
## 项目身份采集（E3-T14）。
##
## 插件只提供原始事实：``res://`` 的真实路径、``project.godot`` 是否存在、
## 项目名与 Godot 版本。项目身份是否可信、是否与已登记记录一致由 Backend 判定，
## 插件不自行生成或比较 ``project_id``。


const PROJECT_FILE := "project.godot"


## 项目根目录的绝对路径（统一使用正斜杠）。
func root_path() -> String:
	return ProjectSettings.globalize_path("res://").replace("\\", "/")


func project_file_path() -> String:
	return root_path().path_join(PROJECT_FILE)


## ``project.godot`` 可读才视为有效项目；缺失时连接应被拒绝。
func is_valid() -> bool:
	return not root_path().is_empty() and FileAccess.file_exists(project_file_path())


func project_name() -> String:
	var configured := str(ProjectSettings.get_setting("application/config/name", ""))
	if not configured.is_empty():
		return configured
	return root_path().get_file()


func godot_version() -> String:
	var info := Engine.get_version_info()
	return str(info.get("string", "unknown"))


## HELLO 中 ``project`` 字段的内容。
func to_hello() -> Dictionary:
	return {
		"root": root_path(),
		"name": project_name(),
		"godot_version": godot_version(),
	}
