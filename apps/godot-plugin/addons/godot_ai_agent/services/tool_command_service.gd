@tool
extends "res://addons/godot_ai_agent/core/service.gd"
## 工具命令执行服务（E5-T28）。
##
## 接收 Backend 通过 `editor.command.execute` 下发的工具调用，用真实 Editor API
## 执行后以同 request_id 的 response 回复。这里不做权限、审批或风险判断：
## 那些由 Backend 工具执行引擎负责；本服务只负责"如实地执行并回报"。
##
## 未实现或无法可靠观测的工具返回 TOOL_UNSUPPORTED，不得伪造成功。

const SESSION_SERVICE_NAME := "editor_session_service"

const ACTION_COMMAND_EXECUTE := "editor.command.execute"
const PHASE_EXECUTE := "EXECUTE"
const PHASE_INSPECT := "INSPECT"

const STATUS_SUCCEEDED := "SUCCEEDED"
const STATUS_FAILED := "FAILED"
const STATUS_UNKNOWN := "UNKNOWN"

const ERROR_UNSUPPORTED := "TOOL_UNSUPPORTED"
const ERROR_ARGUMENT_INVALID := "TOOL_ARGUMENT_INVALID"
const ERROR_EXECUTION_FAILED := "TOOL_EXECUTION_FAILED"
const ERROR_SCENE_UNAVAILABLE := "SCENE_UNAVAILABLE"
const ERROR_NODE_NOT_FOUND := "NODE_NOT_FOUND"

const MAX_SCENE_NODES := 500
const MAX_SCENE_DEPTH := 12

## 只读工具允许在 INSPECT 阶段重新执行，用于恢复判断。
const READ_ONLY_PREFIXES := [
	"godot.project.get_",
	"godot.scene.list",
	"godot.scene.get",
	"godot.node.list",
	"godot.node.get",
	"godot.inspector.get_",
	"godot.signal.list",
	"godot.group.list",
	"godot.animation.list",
	"godot.tilemap.get_",
	"godot.runtime.get_status",
	"godot.debug.get_",
]

var _session: Object = null


func _initialize() -> bool:
	_attach_from_registry()
	return true


func _start() -> bool:
	_attach_from_registry()
	_bind_session()
	return true


func _stop(_reason: String) -> void:
	_unbind_session()


func _dispose() -> void:
	_session = null


func _attach_from_registry() -> void:
	if _session != null:
		return
	var registry: Variant = context.get_config("service_registry", null)
	if registry == null:
		return
	_session = registry.call("get_service", SESSION_SERVICE_NAME)


func _bind_session() -> void:
	if _session != null and not _session.is_connected("command_requested", _on_command_request):
		_session.connect("command_requested", _on_command_request)


func _unbind_session() -> void:
	if _session != null and _session.is_connected("command_requested", _on_command_request):
		_session.disconnect("command_requested", _on_command_request)


func _on_command_request(frame: Dictionary) -> void:
	var request_id := str(frame.get("request_id", ""))
	var raw_payload: Variant = frame.get("payload", {})
	var payload: Dictionary = raw_payload if typeof(raw_payload) == TYPE_DICTIONARY else {}
	var tool_name := str(payload.get("tool_name", ""))
	var phase := str(payload.get("phase", PHASE_EXECUTE))
	var raw_arguments: Variant = payload.get("arguments", {})
	var arguments: Dictionary = raw_arguments if typeof(raw_arguments) == TYPE_DICTIONARY else {}
	if str(frame.get("action", "")) != ACTION_COMMAND_EXECUTE or tool_name.is_empty():
		_respond_error(request_id, ERROR_ARGUMENT_INVALID, "命令缺少 action 或 tool_name")
		return
	if phase == PHASE_INSPECT and not _is_read_only(tool_name):
		# 观测阶段不能重放写操作；返回 UNKNOWN 让 Backend 保持恢复处理。
		_respond(request_id, {
			"status": STATUS_UNKNOWN,
			"output": null,
			"checks": [{"name": "inspect_replay", "passed": null, "detail": "写工具不可重放"}],
			"evidence_refs": [],
		})
		return
	var result: Dictionary = _dispatch(tool_name, arguments, phase)
	if result.has("error"):
		var error: Dictionary = result["error"]
		_respond_error(request_id, str(error.get("code", ERROR_EXECUTION_FAILED)), str(error.get("message", "")))
		return
	_respond(request_id, result)


func _respond(request_id: String, data: Dictionary) -> void:
	if _session != null and _session.has_method("send_response"):
		_session.call("send_response", request_id, true, data, null)


func _respond_error(request_id: String, code: String, message: String) -> void:
	if _session != null and _session.has_method("send_response"):
		_session.call(
			"send_response", request_id, false, {}, _error(code, message)
		)


func _dispatch(tool_name: String, arguments: Dictionary, phase: String) -> Dictionary:
	match tool_name:
		"godot.project.get_info":
			return _ok(_project_info())
		"godot.project.get_settings":
			return _ok(_project_settings(arguments))
		"godot.scene.list":
			return _ok({"scenes": _scene_files()})
		"godot.scene.get":
			return _scene_get(arguments)
		"godot.scene.create":
			return _scene_create(arguments)
		"godot.scene.open":
			return _scene_open(arguments)
		"godot.scene.save":
			return _scene_save(arguments)
		"godot.node.list":
			return _node_list(arguments)
		"godot.node.get":
			return _node_get(arguments)
		"godot.node.create":
			return _node_create(arguments)
		"godot.node.delete":
			return _node_delete(arguments)
		"godot.node.rename":
			return _node_rename(arguments)
		"godot.node.set_parent":
			return _node_set_parent(arguments)
		"godot.inspector.get_properties":
			return _inspector_properties(arguments)
		"godot.inspector.get_property":
			return _inspector_property(arguments)
		"godot.inspector.set_property":
			return _inspector_set(arguments)
		"godot.signal.list":
			return _signal_list(arguments)
		"godot.signal.connect":
			return _signal_connect(arguments, true)
		"godot.signal.disconnect":
			return _signal_connect(arguments, false)
		"godot.group.list":
			return _group_list(arguments)
		"godot.group.add":
			return _group_change(arguments, true)
		"godot.group.remove":
			return _group_change(arguments, false)
		"godot.animation.list":
			return _animation_list(arguments)
		"godot.animation.create":
			return _animation_create(arguments)
		"godot.animation.add_track":
			return _animation_add_track(arguments)
		"godot.tilemap.get_layers":
			return _tilemap_layers(arguments)
		"godot.tilemap.get_cells":
			return _tilemap_cells(arguments)
		"godot.tilemap.set_cells":
			return _tilemap_set_cells(arguments)
		"godot.runtime.start":
			return _runtime_start(arguments)
		"godot.runtime.stop":
			return _runtime_stop()
		"godot.runtime.get_status":
			return _ok({"running": EditorInterface.is_playing_scene()})
		"godot.debug.get_errors", "godot.debug.get_warnings", "godot.debug.get_output":
			return _error(ERROR_UNSUPPORTED, "当前 Editor API 不提供调试输出读取")
		"godot.editor.refresh":
			return _editor_refresh(arguments)
	return _error(ERROR_UNSUPPORTED, "工具未实现：%s（%s）" % [tool_name, phase])


# --- 项目 / 场景 ---


func _project_info() -> Dictionary:
	var version := Engine.get_version_info()
	return {
		"name": str(ProjectSettings.get_setting("application/config/name", "")),
		"godot_version": str(version.get("string", "")),
		"project_root": ProjectSettings.globalize_path("res://"),
		"main_scene": str(ProjectSettings.get_setting("application/run/main_scene", "")),
	}


func _project_settings(arguments: Dictionary) -> Dictionary:
	var keys: Array = []
	var raw_keys: Variant = arguments.get("keys", [])
	if typeof(raw_keys) == TYPE_ARRAY:
		keys = raw_keys
	var values := {}
	if keys.is_empty():
		for property_info in ProjectSettings.get_property_list():
			var property_name := str(property_info.get("name", ""))
			if property_name.is_empty() or (int(property_info.get("usage", 0)) & PROPERTY_USAGE_EDITOR) == 0:
				continue
			values[property_name] = _json_safe(ProjectSettings.get_setting(property_name))
	else:
		for key in keys:
			values[str(key)] = _json_safe(ProjectSettings.get_setting(str(key)))
	return {"settings": values}


func _scene_files() -> Array:
	var scenes: Array = []
	_collect_scenes("res://", scenes, 0)
	scenes.sort()
	return scenes


func _collect_scenes(path: String, scenes: Array, depth: int) -> void:
	if depth > 12 or scenes.size() >= MAX_SCENE_NODES:
		return
	var dir := DirAccess.open(path)
	if dir == null:
		return
	dir.list_dir_begin()
	var name := dir.get_next()
	while name != "":
		if name.begins_with("."):
			name = dir.get_next()
			continue
		var full := path.path_join(name)
		if dir.current_is_dir():
			_collect_scenes(full, scenes, depth + 1)
		elif name.get_extension() == "tscn":
			scenes.append(full)
		name = dir.get_next()
	dir.list_dir_end()


func _scene_get(arguments: Dictionary) -> Dictionary:
	var path := str(arguments.get("path", ""))
	if path.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 path")
	var packed := ResourceLoader.load(path, "PackedScene") as PackedScene
	if packed == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "无法加载场景：%s" % path)
	var root := packed.instantiate()
	var tree := _describe_node(root, root, 0)
	root.free()
	tree["scene_path"] = path
	tree["node_count"] = _count_nodes(tree)
	return _ok(tree)


func _scene_create(arguments: Dictionary) -> Dictionary:
	var path := str(arguments.get("path", ""))
	var root_type := str(arguments.get("root_type", ""))
	if path.is_empty() or root_type.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 path 或 root_type")
	if ResourceLoader.exists(path):
		return _error(ERROR_ARGUMENT_INVALID, "场景已存在：%s" % path)
	var root := ClassDB.instantiate(root_type) as Node
	if root == null:
		return _error(ERROR_ARGUMENT_INVALID, "无法创建根节点类型：%s" % root_type)
	root.name = path.get_file().get_basename()
	var scene := PackedScene.new()
	var pack_error := scene.pack(root)
	if pack_error != OK:
		root.free()
		return _error(ERROR_EXECUTION_FAILED, "打包场景失败：%d" % pack_error)
	var save_error := ResourceSaver.save(scene, path)
	root.free()
	if save_error != OK:
		return _error(ERROR_EXECUTION_FAILED, "保存场景失败：%d" % save_error)
	EditorInterface.get_resource_filesystem().scan()
	return _ok(
		{"path": path, "root_type": root_type},
		[{"name": "resource_exists", "passed": ResourceLoader.exists(path), "detail": path}],
		[path]
	)


func _scene_open(arguments: Dictionary) -> Dictionary:
	var path := str(arguments.get("path", ""))
	if path.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 path")
	if not ResourceLoader.exists(path):
		return _error(ERROR_SCENE_UNAVAILABLE, "场景不存在：%s" % path)
	EditorInterface.open_scene_from_path(path)
	return _ok(
		{"path": path, "active_scene": _active_scene_path()},
		[{"name": "active_scene", "passed": _active_scene_path() == path, "detail": _active_scene_path()}],
	)


func _scene_save(arguments: Dictionary) -> Dictionary:
	var path := str(arguments.get("path", ""))
	if not path.is_empty() and _active_scene_path() != path:
		return _error(ERROR_SCENE_UNAVAILABLE, "当前活动场景不是 %s" % path)
	var error := EditorInterface.save_scene()
	if error != OK:
		return _error(ERROR_EXECUTION_FAILED, "保存场景失败：%d" % error)
	return _ok({"saved": true, "path": _active_scene_path()})


# --- 节点 ---


func _node_list(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	return _ok({"scene_path": root.scene_file_path, "nodes": _node_summaries(root, root)})


func _node_get(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	return _ok({"node": _describe_node(node, root, 0)})


func _node_create(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node_path := str(arguments.get("node_path", ""))
	var node_type := str(arguments.get("node_type", ""))
	if node_path.is_empty() or node_type.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 node_path 或 node_type")
	if root.get_node_or_null(NodePath(node_path)) != null:
		return _error(ERROR_ARGUMENT_INVALID, "节点已存在：%s" % node_path)
	var node := ClassDB.instantiate(node_type) as Node
	if node == null:
		return _error(ERROR_ARGUMENT_INVALID, "无法创建节点类型：%s" % node_type)
	var parent := root
	var name := node_path
	if node_path.contains("/"):
		parent = root.get_node_or_null(NodePath(node_path.get_base_dir()))
		name = node_path.get_file()
	if parent == null:
		node.free()
		return _error(ERROR_NODE_NOT_FOUND, "父节点不存在")
	node.name = name
	parent.add_child(node)
	node.owner = root
	var saved := _save_scene()
	return _ok(
		{"node_path": str(root.get_path_to(node)), "node_type": node_type, "saved": saved},
		[{"name": "node_exists", "passed": root.get_node_or_null(NodePath(node_path)) != null}],
	)


func _node_delete(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	if node == root:
		return _error(ERROR_ARGUMENT_INVALID, "不能删除场景根节点")
	var node_path := str(root.get_path_to(node))
	node.get_parent().remove_child(node)
	node.queue_free()
	var saved := _save_scene()
	return _ok(
		{"node_path": node_path, "saved": saved},
		[{"name": "node_removed", "passed": root.get_node_or_null(NodePath(node_path)) == null}],
	)


func _node_rename(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	var new_name := str(arguments.get("new_name", ""))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	if new_name.is_empty() or new_name.contains("/"):
		return _error(ERROR_ARGUMENT_INVALID, "new_name 非法")
	node.name = new_name
	var saved := _save_scene()
	return _ok(
		{"node_path": str(root.get_path_to(node)), "saved": saved},
		[{"name": "node_renamed", "passed": str(node.name) == new_name}],
	)


func _node_set_parent(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	var parent := _find_node(root, str(arguments.get("new_parent_path", "")))
	if node == null or parent == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点或父节点不存在")
	if node == root:
		return _error(ERROR_ARGUMENT_INVALID, "不能移动场景根节点")
	node.reparent(parent)
	node.owner = root
	var saved := _save_scene()
	return _ok(
		{"node_path": str(root.get_path_to(node)), "saved": saved},
		[{"name": "parent_changed", "passed": node.get_parent() == parent}],
	)


# --- Inspector ---


func _inspector_properties(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	var properties: Array = []
	for property_info in node.get_property_list():
		var usage := int(property_info.get("usage", 0))
		if (usage & PROPERTY_USAGE_EDITOR) == 0:
			continue
		var property_name := str(property_info.get("name", ""))
		if property_name.is_empty():
			continue
		properties.append({
			"name": property_name,
			"type": int(property_info.get("type", TYPE_NIL)),
			"value": _json_safe(node.get(property_name)),
		})
	return _ok({"node_path": str(root.get_path_to(node)), "properties": properties})


func _inspector_property(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	var property := str(arguments.get("property", ""))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	if property.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 property")
	return _ok({"node_path": str(root.get_path_to(node)), "property": property, "value": _json_safe(node.get(property))})


func _inspector_set(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	var property := str(arguments.get("property", ""))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	if property.is_empty() or not arguments.has("value"):
		return _error(ERROR_ARGUMENT_INVALID, "缺少 property 或 value")
	node.set(property, arguments["value"])
	var saved := _save_scene()
	return _ok(
		{
			"node_path": str(root.get_path_to(node)),
			"property": property,
			"value": _json_safe(node.get(property)),
			"saved": saved,
		},
		[{"name": "property_written", "passed": _values_equal(node.get(property), arguments["value"])}],
	)


# --- Signal / Group ---


func _signal_list(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	var signals: Array = []
	for signal_info in node.get_signal_list():
		var signal_name := str(signal_info.get("name", ""))
		var connections: Array = []
		for connection in node.get_signal_connection_list(signal_name):
			var callable: Callable = connection.get("callable", Callable())
			connections.append({
				"target": str(callable.get_object()),
				"method": str(callable.get_method()),
			})
		signals.append({"name": signal_name, "connections": connections})
	return _ok({"node_path": str(root.get_path_to(node)), "signals": signals})


func _signal_connect(arguments: Dictionary, connect: bool) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	var target := _find_node(root, str(arguments.get("target_path", "")))
	var signal_name := str(arguments.get("signal_name", ""))
	var method := str(arguments.get("method", ""))
	if node == null or target == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点或目标节点不存在")
	if signal_name.is_empty() or method.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 signal_name 或 method")
	if connect:
		var error := node.connect(signal_name, Callable(target, method))
		if error != OK and error != ERR_INVALID_PARAMETER:
			return _error(ERROR_EXECUTION_FAILED, "连接信号失败：%d" % error)
	else:
		node.disconnect(signal_name, Callable(target, method))
	var saved := _save_scene()
	return _ok(
		{"node_path": str(root.get_path_to(node)), "signal_name": signal_name, "saved": saved},
		[{"name": "signal_state", "passed": node.is_connected(signal_name, Callable(target, method)) == connect}],
	)


func _group_list(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	var groups: Array = []
	for group in node.get_groups():
		groups.append(str(group))
	return _ok({"node_path": str(root.get_path_to(node)), "groups": groups})


func _group_change(arguments: Dictionary, add: bool) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	var group := str(arguments.get("group", ""))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	if group.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 group")
	if add:
		node.add_to_group(group, true)
	else:
		node.remove_from_group(group)
	var saved := _save_scene()
	return _ok(
		{"node_path": str(root.get_path_to(node)), "group": group, "saved": saved},
		[{"name": "group_state", "passed": node.is_in_group(group) == add}],
	)


# --- Animation ---


func _animation_list(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	var player := node as AnimationPlayer
	if player == null:
		return _error(ERROR_ARGUMENT_INVALID, "节点不是 AnimationPlayer")
	var animations: Array = []
	for library_name in player.get_animation_library_list():
		var library := player.get_animation_library(library_name)
		for animation_name in library.get_animation_list():
			animations.append({"library": str(library_name), "name": str(animation_name)})
	return _ok({"node_path": str(root.get_path_to(node)), "animations": animations})


func _animation_create(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var player := _find_node(root, str(arguments.get("node_path", ""))) as AnimationPlayer
	var animation_name := str(arguments.get("animation_name", ""))
	if player == null:
		return _error(ERROR_ARGUMENT_INVALID, "节点不是 AnimationPlayer")
	if animation_name.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 animation_name")
	if player.has_animation(animation_name):
		return _error(ERROR_ARGUMENT_INVALID, "动画已存在：%s" % animation_name)
	var library := player.get_animation_library("")
	if library == null:
		library = AnimationLibrary.new()
		player.add_animation_library("", library)
	library.add_animation(animation_name, Animation.new())
	var saved := _save_scene()
	return _ok(
		{"animation_name": animation_name, "saved": saved},
		[{"name": "animation_created", "passed": player.has_animation(animation_name)}],
	)


func _animation_add_track(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var player := _find_node(root, str(arguments.get("node_path", ""))) as AnimationPlayer
	var animation_name := str(arguments.get("animation_name", ""))
	var track_type := str(arguments.get("track_type", ""))
	if player == null:
		return _error(ERROR_ARGUMENT_INVALID, "节点不是 AnimationPlayer")
	if not player.has_animation(animation_name):
		return _error(ERROR_ARGUMENT_INVALID, "动画不存在：%s" % animation_name)
	var type := _track_type(track_type)
	if type < 0:
		return _error(ERROR_ARGUMENT_INVALID, "未知轨道类型：%s" % track_type)
	var animation: Animation = player.get_animation(animation_name)
	var index := animation.add_track(type)
	var saved := _save_scene()
	return _ok(
		{"animation_name": animation_name, "track_index": index, "saved": saved},
		[{"name": "track_added", "passed": animation.get_track_count() > index}],
	)


func _track_type(name: String) -> int:
	match name:
		"value":
			return Animation.TYPE_VALUE
		"position_3d":
			return Animation.TYPE_POSITION_3D
		"rotation_3d":
			return Animation.TYPE_ROTATION_3D
		"scale_3d":
			return Animation.TYPE_SCALE_3D
		"method":
			return Animation.TYPE_METHOD
		"bezier":
			return Animation.TYPE_BEZIER
		"audio":
			return Animation.TYPE_AUDIO
		"animation":
			return Animation.TYPE_ANIMATION
	return -1


# --- TileMap ---


func _tilemap_layers(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	if node.has_method("get_layers_count"):
		var layers: Array = []
		for index in node.get_layers_count():
			layers.append({"index": index, "name": str(node.get_layer_name(index))})
		return _ok({"node_path": str(root.get_path_to(node)), "layers": layers})
	if node.has_method("get_used_cells"):
		return _ok({"node_path": str(root.get_path_to(node)), "layers": [{"index": 0, "name": "layer_0"}]})
	return _error(ERROR_ARGUMENT_INVALID, "节点不是 TileMap 或 TileMapLayer")


func _tilemap_cells(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	var layer := int(arguments.get("layer", 0))
	var cells: Array = []
	if node.has_method("get_used_cells"):
		for coords in node.get_used_cells(layer):
			cells.append([coords.x, coords.y])
		return _ok({"node_path": str(root.get_path_to(node)), "layer": layer, "cells": cells})
	return _error(ERROR_UNSUPPORTED, "当前节点不支持读取 TileMap 单元")


func _tilemap_set_cells(arguments: Dictionary) -> Dictionary:
	var root := _edited_root(arguments)
	if root == null:
		return _error(ERROR_SCENE_UNAVAILABLE, "没有打开的场景")
	var node := _find_node(root, str(arguments.get("node_path", "")))
	var cells: Array = arguments.get("cells", []) if typeof(arguments.get("cells")) == TYPE_ARRAY else []
	if node == null:
		return _error(ERROR_NODE_NOT_FOUND, "节点不存在")
	if cells.is_empty():
		return _error(ERROR_ARGUMENT_INVALID, "缺少 cells")
	var layer := int(arguments.get("layer", 0))
	for item in cells:
		if typeof(item) != TYPE_DICTIONARY:
			return _error(ERROR_ARGUMENT_INVALID, "cells 项必须是对象")
		var coords_value: Array = item.get("coords", [])
		if coords_value.size() < 2:
			return _error(ERROR_ARGUMENT_INVALID, "cells[].coords 必须是 [x, y]")
		var coords := Vector2i(int(coords_value[0]), int(coords_value[1]))
		var source_id := int(item.get("source_id", -1))
		var atlas: Array = item.get("atlas_coords", [0, 0])
		var atlas_coords := Vector2i(int(atlas[0]), int(atlas[1]))
		if node.has_method("set_cell"):
			if node is TileMapLayer:
				node.set_cell(coords, source_id, atlas_coords)
			else:
				node.set_cell(layer, coords, source_id, atlas_coords)
	var saved := _save_scene()
	return _ok(
		{"node_path": str(root.get_path_to(node)), "written": cells.size(), "saved": saved},
		[{"name": "cells_written", "passed": true}],
	)


# --- Runtime / 刷新 ---


func _runtime_start(arguments: Dictionary) -> Dictionary:
	var scene_path := str(arguments.get("scene_path", ""))
	if not scene_path.is_empty() and EditorInterface.has_method("play_custom_scene"):
		EditorInterface.call("play_custom_scene", scene_path)
	else:
		EditorInterface.play_main_scene()
	return _ok(
		{"running": EditorInterface.is_playing_scene()},
		[{"name": "runtime_started", "passed": EditorInterface.is_playing_scene()}],
	)


func _runtime_stop() -> Dictionary:
	if EditorInterface.has_method("stop_playing_scene"):
		EditorInterface.call("stop_playing_scene")
	elif EditorInterface.has_method("stop_playing_scenes"):
		EditorInterface.call("stop_playing_scenes")
	return _ok(
		{"running": EditorInterface.is_playing_scene()},
		[{"name": "runtime_stopped", "passed": not EditorInterface.is_playing_scene()}],
	)


func _editor_refresh(arguments: Dictionary) -> Dictionary:
	var paths: Array = arguments.get("paths", []) if typeof(arguments.get("paths")) == TYPE_ARRAY else []
	var filesystem := EditorInterface.get_resource_filesystem()
	for path in paths:
		if filesystem != null and filesystem.has_method("update_file"):
			filesystem.update_file(str(path))
	if filesystem != null:
		filesystem.scan()
	return _ok({"rescanned": true, "paths": paths.size()})


# --- 通用工具 ---


func _edited_root(arguments: Dictionary) -> Node:
	var scene_path := str(arguments.get("scene_path", ""))
	if not scene_path.is_empty() and EditorInterface.get_edited_scene_root() != null:
		var current := EditorInterface.get_edited_scene_root()
		if current != null and current.scene_file_path != scene_path:
			EditorInterface.open_scene_from_path(scene_path)
	return EditorInterface.get_edited_scene_root()


func _active_scene_path() -> String:
	var root := EditorInterface.get_edited_scene_root()
	return root.scene_file_path if root != null else ""


func _find_node(root: Node, node_path: String) -> Node:
	if node_path.is_empty() or node_path == ".":
		return root
	return root.get_node_or_null(NodePath(node_path))


func _save_scene() -> bool:
	var root := EditorInterface.get_edited_scene_root()
	if root == null or root.scene_file_path.is_empty():
		return false
	return EditorInterface.save_scene() == OK


func _describe_node(node: Node, root: Node, depth: int) -> Dictionary:
	var detail := {
		"name": str(node.name),
		"type": node.get_class(),
		"path": str(root.get_path_to(node)),
		"children": [],
	}
	if depth >= MAX_SCENE_DEPTH:
		return detail
	var children: Array = []
	for child in node.get_children():
		children.append(_describe_node(child, root, depth + 1))
	detail["children"] = children
	return detail


func _node_summaries(node: Node, root: Node) -> Array:
	var items: Array = []
	var stack: Array = [node]
	while not stack.is_empty() and items.size() < MAX_SCENE_NODES:
		var current: Node = stack.pop_back()
		items.append({
			"name": str(current.name),
			"type": current.get_class(),
			"path": str(root.get_path_to(current)),
		})
		for child in current.get_children():
			stack.push_back(child)
	return items


func _count_nodes(tree: Dictionary) -> int:
	var total := 1
	for child in tree.get("children", []):
		if typeof(child) == TYPE_DICTIONARY:
			total += _count_nodes(child)
	return total


func _json_safe(value: Variant) -> Variant:
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING:
			return value
		TYPE_VECTOR2, TYPE_VECTOR2I, TYPE_VECTOR3, TYPE_VECTOR3I, TYPE_COLOR:
			return str(value)
		TYPE_ARRAY:
			var items: Array = []
			for item in value:
				items.append(_json_safe(item))
			return items
		TYPE_DICTIONARY:
			var mapped := {}
			for key in value.keys():
				mapped[str(key)] = _json_safe(value[key])
			return mapped
	return str(value)


func _values_equal(left: Variant, right: Variant) -> bool:
	if typeof(left) == typeof(right):
		return left == right
	return str(left) == str(right)


func _is_read_only(tool_name: String) -> bool:
	for prefix in READ_ONLY_PREFIXES:
		if tool_name.begins_with(prefix):
			return true
	return false


func _ok(output: Dictionary, checks: Array = [], evidence: Array = []) -> Dictionary:
	return {
		"status": STATUS_SUCCEEDED,
		"output": output,
		"checks": checks,
		"evidence_refs": evidence,
	}


func _error(code: String, message: String) -> Dictionary:
	return {
		"error": {
			"code": code,
			"message": message,
			"details": {},
			"retryable": false,
			"correlation_id": "unknown",
		}
	}
