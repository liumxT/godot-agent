"""Repository 基础设施（E1-T05）。

约定：

- 每个业务模块拥有自己的 Repository，禁止跨模块导入；
- Repository 只接收会话、不创建引擎、不提交事务；
- 查询与写入异常统一翻译为 ``DatabaseError``；
- 列表查询必须分页，``limit`` 限制在 1–200，``offset`` 不得为负。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.errors import translate_db_error

MIN_LIMIT = 1
MAX_LIMIT = 200
DEFAULT_LIMIT = 50


@dataclass(frozen=True)
class Page[ModelT]:
    """统一分页结果。"""

    items: list[ModelT]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class BaseRepository[ModelT]:
    """仓储基类：子类只需声明 ``model``。"""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def get(self, entity_id: Any) -> ModelT | None:
        try:
            return await self._session.get(self.model, entity_id)
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc

    async def add(self, entity: ModelT) -> ModelT:
        """加入会话并 flush，使约束错误在写入点暴露；不提交。"""

        try:
            self._session.add(entity)
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc
        return entity

    async def delete(self, entity: ModelT) -> None:
        try:
            await self._session.delete(entity)
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc

    async def paginate(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        filters: Sequence[ColumnElement[bool]] = (),
    ) -> Page[ModelT]:
        if not MIN_LIMIT <= limit <= MAX_LIMIT:
            raise ValueError(f"limit 必须在 {MIN_LIMIT}–{MAX_LIMIT} 之间")
        if offset < 0:
            raise ValueError("offset 不能为负数")

        statement = select(self.model)
        if filters:
            statement = statement.where(*filters)

        try:
            total = (
                await self._session.scalar(select(func.count()).select_from(statement.subquery()))
            ) or 0
            rows = (
                await self._session.scalars(
                    statement.order_by(*self._order_columns()).limit(limit).offset(offset)
                )
            ).all()
        except SQLAlchemyError as exc:
            raise translate_db_error(exc) from exc

        return Page(items=list(rows), total=int(total), limit=limit, offset=offset)

    def _order_columns(self) -> tuple[Any, ...]:
        """默认按主键排序，保证分页结果稳定。"""

        return tuple(inspect(self.model).primary_key)
