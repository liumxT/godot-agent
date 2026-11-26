extends Node2D
## Level 01 构建器：用数据表生成 TileMapLayer 地形与实体。
##
## 单元格与实体都由本脚本确定，避免二进制 tile_map_data，
## 从而让关卡布局在代码审查与结构校验中可读。

const TILE := 16
const LEVEL_WIDTH := 160
const GROUND_Y := 20
const GROUND_TILE := Vector2i(0, 0)
const PLATFORM_TILE := Vector2i(1, 0)

const PLAYER_SCENE := preload("res://scenes/player/player.tscn")
const ENEMY_SCENE := preload("res://scenes/enemies/patrol_enemy.tscn")
const COLLECTIBLE_SCENE := preload("res://scenes/collectibles/collectible.tscn")
const SPIKE_SCENE := preload("res://scenes/levels/spike.tscn")
const GOAL_SCENE := preload("res://scenes/levels/goal.tscn")

## [x_start, x_end, y]
const PLATFORM_ROWS := [
	[26, 33, 17],
	[36, 43, 14],
	[46, 53, 11],
	[60, 67, 16],
	[70, 77, 19],
	[82, 90, 18],
	[110, 118, 16],
	[121, 129, 13],
	[132, 140, 10],
]

const COIN_TILES := [
	Vector2i(8, 18),
	Vector2i(12, 18),
	Vector2i(16, 18),
	Vector2i(30, 15),
	Vector2i(39, 12),
	Vector2i(46, 9),
	Vector2i(64, 14),
	Vector2i(74, 17),
	Vector2i(86, 16),
	Vector2i(114, 14),
	Vector2i(121, 11),
	Vector2i(132, 8),
]

const GEM_TILES := [Vector2i(52, 9), Vector2i(128, 11), Vector2i(139, 8)]
const SPIKE_TILES := [Vector2i(57, GROUND_Y), Vector2i(72, GROUND_Y)]

## [x_tile, patrol_range]
const ENEMIES := [[86, 64], [104, 48]]

@onready var ground: TileMapLayer = $Ground
@onready var platforms: TileMapLayer = $Platforms
@onready var entities: Node2D = $Entities
@onready var player_spawn: Marker2D = $PlayerSpawn


func _ready() -> void:
	_build_terrain()
	_spawn_player()
	_spawn_spikes()
	_spawn_enemies()
	_spawn_collectibles()
	_spawn_goal()


func _build_terrain() -> void:
	for x in range(LEVEL_WIDTH):
		for y in [GROUND_Y, GROUND_Y + 1, GROUND_Y + 2]:
			ground.set_cell(Vector2i(x, y), 0, GROUND_TILE)
	for y in range(0, GROUND_Y):
		ground.set_cell(Vector2i(0, y), 0, GROUND_TILE)
		ground.set_cell(Vector2i(LEVEL_WIDTH - 1, y), 0, GROUND_TILE)
	for row in PLATFORM_ROWS:
		for x in range(int(row[0]), int(row[1]) + 1):
			platforms.set_cell(Vector2i(x, int(row[2])), 0, PLATFORM_TILE)


func _spawn_player() -> void:
	var player = PLAYER_SCENE.instantiate()
	player.position = player_spawn.position
	entities.add_child(player)


func _spawn_spikes() -> void:
	for tile in SPIKE_TILES:
		var spike = SPIKE_SCENE.instantiate()
		spike.position = Vector2(tile.x * TILE + 24.0, tile.y * TILE - 8.0)
		entities.add_child(spike)


func _spawn_enemies() -> void:
	for entry in ENEMIES:
		var enemy = ENEMY_SCENE.instantiate()
		enemy.position = Vector2(int(entry[0]) * TILE, GROUND_Y * TILE - 14.0)
		enemy.patrol_range = float(entry[1])
		entities.add_child(enemy)


func _spawn_collectibles() -> void:
	for tile in COIN_TILES:
		var coin = COLLECTIBLE_SCENE.instantiate()
		coin.kind = "coin"
		coin.value = 10
		coin.position = _tile_center(tile)
		entities.add_child(coin)
	for tile in GEM_TILES:
		var gem = COLLECTIBLE_SCENE.instantiate()
		gem.kind = "gem"
		gem.value = 50
		gem.position = _tile_center(tile)
		entities.add_child(gem)


func _spawn_goal() -> void:
	var goal = GOAL_SCENE.instantiate()
	goal.position = Vector2(150 * TILE, GROUND_Y * TILE)
	entities.add_child(goal)


func _tile_center(tile: Vector2i) -> Vector2:
	return Vector2(tile.x * TILE + TILE * 0.5, tile.y * TILE + TILE * 0.5)
