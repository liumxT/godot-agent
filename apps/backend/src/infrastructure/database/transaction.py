"""事务边界管理（E1-T06）。

规则（对应设计文档 §5.5）：

- 最外层开启事务，正常退出提交，异常回滚；
- 已在事务中则加入外层，不启用 savepoint（E1-Q3）；
- ``timeout`` 通过 ``asyncio.timeout`` 包裹，超时回滚并抛
  ``OperationTimeout(TRANSACTION_TIMEOUT)``；
- 超时后的会话标记为失效，禁止继续复用；
- Repository 不调用本模块，事务边界只能出现在 Service / 应用层。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DatabaseError, OperationTimeout

_DEPTH_KEY = "transaction_depth"
_INVALID_KEY = "session_invalidated"


@asynccontextmanager
async def transaction(
    session: AsyncSession,
    *,
    timeout: float | None = None,
) -> AsyncIterator[AsyncSession]:
    """进入事务作用域；嵌套调用加入外层事务。"""

    if session.info.get(_INVALID_KEY):
        raise DatabaseError("数据库会话已失效，禁止继续使用")

    depth = session.info.get(_DEPTH_KEY, 0)
    if depth > 0:
        # 加入外层：不提交、不回滚、不启用 savepoint
        session.info[_DEPTH_KEY] = depth + 1
        try:
            yield session
        finally:
            session.info[_DEPTH_KEY] = depth
        return

    session.info[_DEPTH_KEY] = 1
    # 会话可能已因自动开始语句处于事务中，此时由本作用域负责结束
    owns = not session.in_transaction()
    try:
        if timeout is None:
            if owns:
                async with session.begin():
                    yield session
            else:
                yield session
                await session.commit()
        else:
            async with asyncio.timeout(timeout):
                if owns:
                    async with session.begin():
                        yield session
                else:
                    yield session
                    await session.commit()
    except TimeoutError:
        await session.rollback()
        session.info[_INVALID_KEY] = True
        raise OperationTimeout(
            "数据库事务超时，已回滚",
            code="TRANSACTION_TIMEOUT",
            details={"timeout": timeout},
        ) from None
    except BaseException:
        await session.rollback()
        raise
    finally:
        session.info[_DEPTH_KEY] = 0
