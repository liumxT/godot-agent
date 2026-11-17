"""启动装配包。"""

from bootstrap.application import create_app
from bootstrap.lifecycle import Lifecycle

__all__ = ["create_app", "Lifecycle"]
