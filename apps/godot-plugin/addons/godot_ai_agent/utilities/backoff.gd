@tool
extends RefCounted
## 指数退避策略（E3-T03 / T12）。
##
## 默认序列 0.5 / 1 / 2 / 4 / 8 秒，上限取最后一档；每次取值带 ±20% 抖动。
## 只负责计算等待时间，不持有计时器，调用方用单调时钟驱动。


const DEFAULT_STEPS: Array = [0.5, 1.0, 2.0, 4.0, 8.0]

var _steps: Array = []
var _jitter_ratio := 0.2
var _index := 0
var _rng := RandomNumberGenerator.new()


func _init(steps: Array = [], jitter_ratio: float = 0.2) -> void:
	_steps = DEFAULT_STEPS.duplicate() if steps.is_empty() else steps.duplicate()
	_jitter_ratio = jitter_ratio
	_rng.randomize()


## 固定随机种子，供测试使用。
func set_seed(seed_value: int) -> void:
	_rng.seed = seed_value


func reset() -> void:
	_index = 0


func attempt_index() -> int:
	return _index


## 返回本次等待秒数，并推进到下一档（到上限后保持不变）。
func next_delay() -> float:
	var base := float(_steps[mini(_index, _steps.size() - 1)])
	if _index < _steps.size() - 1:
		_index += 1
	var jitter := _rng.randf_range(-_jitter_ratio, _jitter_ratio)
	return maxf(0.0, base * (1.0 + jitter))


## 当前档位基准值（不含抖动），用于展示与测试。
func current_base() -> float:
	return float(_steps[mini(_index, _steps.size() - 1)])
