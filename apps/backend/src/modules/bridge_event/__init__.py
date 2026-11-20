"""Bridge 事件流服务（E3-T10）。

只持久化 ``PERSISTENT`` 事件；``EPHEMERAL`` 事件仅确认不落库。
``sequence`` 由 Backend 按 ``(session_id, direction)`` 单调分配。
"""
