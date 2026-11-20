"""数据库异常分类（E1-T03）。

SQLAlchemy 异常不得透出到 API：统一翻译为 ``DatabaseError``，并按原因区分
错误码与可重试性（见 ``packages/contracts/errors/error-codes.json``）。
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from core.errors import DatabaseError

_REASON_LIMIT = 300


def summarize_error(exc: BaseException, *, limit: int = _REASON_LIMIT) -> str:
    """生成可记录的错误摘要：单行、限长、去掉换行。"""

    message = " ".join(str(exc).split())
    if len(message) > limit:
        message = message[: limit - 3] + "..."
    return message


def is_readonly_error(exc: BaseException) -> bool:
    """判断是否属于文件不可写/只读类错误。

    启动阶段这类错误直接以 ``StartupError`` 阻断，避免带病运行。
    """

    text = str(exc).lower()
    markers = ("readonly", "read-only", "permission denied", "unable to open", "disk i/o")
    return any(marker in text for marker in markers)


def translate_db_error(exc: BaseException) -> DatabaseError:
    """把 SQLAlchemy 异常翻译为领域异常；已是领域异常时原样返回。"""

    if isinstance(exc, DatabaseError):
        return exc
    if isinstance(exc, IntegrityError):
        return DatabaseError(
            "数据库约束校验失败",
            code="DATABASE_INTEGRITY_ERROR",
            retryable=False,
            details={"reason": summarize_error(exc)},
        )
    if isinstance(exc, OperationalError):
        return DatabaseError(
            "数据库暂不可用",
            retryable=True,
            details={"reason": summarize_error(exc)},
        )
    if isinstance(exc, SQLAlchemyError):
        return DatabaseError(
            "数据库访问失败",
            retryable=False,
            details={"reason": summarize_error(exc)},
        )
    return DatabaseError("数据库访问失败", details={"reason": summarize_error(exc)})
