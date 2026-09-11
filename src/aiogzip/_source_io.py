"""Private source-position evidence and aiofiles native-call adapters."""

import inspect
from typing import Any, Optional

from aiofiles.threadpool.binary import (
    AsyncBufferedIOBase,
    AsyncBufferedReader,
    AsyncFileIO,
)


def _source_position(source: Any) -> Optional[int]:
    """Snapshot a conforming source's synchronous byte cursor, if available.

    The source contract must make this cursor authoritative for consumption and
    forbid hidden work after read/seek returns or raises. Async tell methods do
    not provide a synchronous checkpoint and are deliberately not invoked.
    """
    try:
        tell = getattr(source, "tell", None)
        if not callable(tell) or inspect.iscoroutinefunction(tell):
            return None
        position = tell()
    except Exception:
        return None
    if inspect.iscoroutine(position):
        position.close()
    return position if type(position) is int and position >= 0 else None


def _is_native_source(source: Any, method: str) -> bool:
    """Recognize aiofiles' supported binary delegates without bypassing overrides."""
    return type(source) in (AsyncBufferedIOBase, AsyncBufferedReader, AsyncFileIO) and (
        method not in vars(source)
    )


class _NativeSourceCall:
    """Publish failure-position evidence only after a native call has stopped."""

    __slots__ = ("source", "method", "args", "no_effect")

    def __init__(self, source: Any, method: str, args: tuple[Any, ...]) -> None:
        self.source = source
        self.method = method
        self.args = args
        self.no_effect = False

    def __call__(self) -> Any:
        before = _source_position(self.source)
        try:
            return getattr(self.source, self.method)(*self.args)
        except BaseException:
            self.no_effect = (
                before is not None and _source_position(self.source) == before
            )
            raise
