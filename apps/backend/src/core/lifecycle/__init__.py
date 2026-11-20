"""生命周期状态机与有序步骤管理（E1-T01）。"""

from core.lifecycle.manager import LifecycleManager, LifecycleStep
from core.lifecycle.states import LifecycleState, can_transition

__all__ = ["LifecycleManager", "LifecycleState", "LifecycleStep", "can_transition"]
