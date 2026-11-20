@tool
extends RefCounted
## 租约数据模型（E3-T08）。
##
## 纯数据解析与本地过期判断；插件只缓存租约，不得自行延长或复活。


const STATUS_ACTIVE := "ACTIVE"
const STATUS_RENEWING := "RENEWING"
const STATUS_EXPIRED := "EXPIRED"
const STATUS_REVOKED := "REVOKED"

const FIELDS := [
	"lease_id",
	"session_id",
	"project_id",
	"fencing_token",
	"status",
	"issued_at",
	"expires_at",
]


## 解析后端下发的 lease payload；结构不合法时返回空字典。
static func parse(data: Variant) -> Dictionary:
	if typeof(data) != TYPE_DICTIONARY:
		return {}
	var source: Dictionary = data
	for field in FIELDS:
		if not source.has(field):
			return {}
	if str(source["lease_id"]).is_empty():
		return {}
	if int(source.get("fencing_token", 0)) <= 0:
		return {}
	var status := str(source["status"])
	if not [STATUS_ACTIVE, STATUS_RENEWING, STATUS_EXPIRED, STATUS_REVOKED].has(status):
		return {}
	return {
		"lease_id": str(source["lease_id"]),
		"session_id": str(source["session_id"]),
		"project_id": str(source["project_id"]),
		"fencing_token": int(source["fencing_token"]),
		"status": status,
		"issued_at": str(source["issued_at"]),
		"renewed_at": str(source.get("renewed_at", "")),
		"expires_at": str(source["expires_at"]),
		"revoked_at": str(source.get("revoked_at", "")),
	}


## 本地只读判断：Status 必须 ACTIVE 且当前时间早于 expires_at。
static func is_usable(lease: Dictionary, now_unix: int = -1) -> bool:
	if lease.is_empty():
		return false
	if str(lease.get("status", "")) != STATUS_ACTIVE:
		return false
	var expires_at := _unix(str(lease.get("expires_at", "")))
	if expires_at <= 0:
		return false
	var now := now_unix if now_unix >= 0 else int(Time.get_unix_time_from_system())
	return now < expires_at


static func remaining_seconds(lease: Dictionary, now_unix: int = -1) -> int:
	var expires_at := _unix(str(lease.get("expires_at", "")))
	if expires_at <= 0:
		return 0
	var now := now_unix if now_unix >= 0 else int(Time.get_unix_time_from_system())
	return maxi(0, expires_at - now)


static func _unix(value: String) -> int:
	if value.is_empty():
		return 0
	var parsed := int(Time.get_unix_time_from_datetime_string(value.trim_suffix("Z")))
	if parsed <= 0:
		return 0
	return parsed
