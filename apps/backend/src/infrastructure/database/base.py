"""Declarative Base（E2）。

E1 只使用手写迁移，没有业务实体；E2 起领域模块共享同一份元数据基类。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有领域实体的基类。"""
