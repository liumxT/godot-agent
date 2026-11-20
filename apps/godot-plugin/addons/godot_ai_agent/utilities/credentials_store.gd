@tool
extends RefCounted
## 客户端凭证存储（E3-T06）。
##
## 凭证属于设备级用户数据（``user://``），不写入项目目录、不进入日志。
## 任何错误只返回错误码，绝不拼接 secret 内容。


const DEFAULT_PATH := "user://godot_ai_agent/credentials.json"

const ERROR_NONE := ""
const ERROR_MISSING := "CREDENTIALS_MISSING"
const ERROR_CORRUPT := "CREDENTIALS_CORRUPT"
const ERROR_IO := "CREDENTIALS_IO_ERROR"

var _path := DEFAULT_PATH
var _client_id := ""
var _client_secret := ""
var _error_code := ERROR_MISSING


func _init(path: String = DEFAULT_PATH) -> void:
	_path = path


func get_path() -> String:
	return _path


func client_id() -> String:
	return _client_id


func client_secret() -> String:
	return _client_secret


func has_credentials() -> bool:
	return not _client_id.is_empty() and not _client_secret.is_empty()


func last_error() -> String:
	return _error_code


## 读取凭证；失败时清空内存中的值并给出错误码。
func load_credentials() -> bool:
	_client_id = ""
	_client_secret = ""
	_error_code = ERROR_MISSING
	if not FileAccess.file_exists(_path):
		return false
	var file := FileAccess.open(_path, FileAccess.READ)
	if file == null:
		_error_code = ERROR_IO
		return false
	var text := file.get_as_text()
	file.close()
	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		_error_code = ERROR_CORRUPT
		return false
	var data: Dictionary = parsed
	_client_id = str(data.get("client_id", ""))
	_client_secret = str(data.get("client_secret", ""))
	if not has_credentials():
		_client_id = ""
		_client_secret = ""
		_error_code = ERROR_CORRUPT
		return false
	_error_code = ERROR_NONE
	return true


func save_credentials(client_id: String, client_secret: String) -> bool:
	if client_id.is_empty() or client_secret.is_empty():
		_error_code = ERROR_CORRUPT
		return false
	var directory := _path.get_base_dir()
	if not DirAccess.dir_exists_absolute(directory):
		var made := DirAccess.make_dir_recursive_absolute(directory)
		if made != OK:
			_error_code = ERROR_IO
			return false
	var file := FileAccess.open(_path, FileAccess.WRITE)
	if file == null:
		_error_code = ERROR_IO
		return false
	file.store_string(JSON.stringify({
		"client_id": client_id,
		"client_secret": client_secret,
		"created_at": Time.get_datetime_string_from_system(true) + "Z",
	}))
	file.close()
	_client_id = client_id
	_client_secret = client_secret
	_error_code = ERROR_NONE
	return true


func clear() -> void:
	_client_id = ""
	_client_secret = ""
	_error_code = ERROR_MISSING
	if FileAccess.file_exists(_path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(_path))


## 日志脱敏：只保留前缀与长度，永不出现在事件字段中。
static func mask(value: String) -> String:
	if value.is_empty():
		return ""
	if value.length() <= 8:
		return "***"
	return "%s***%d" % [value.substr(0, 4), value.length()]
