"""Private source-position evidence and aiofiles native-call ownership."""

import asyncio
import inspect
import threading
from typing import Any, Optional

from aiofiles.threadpool.binary import (
    AsyncBufferedIOBase,
    AsyncBufferedReader,
    AsyncFileIO,
)


def _source_position(source: Any) -> Optional[int]:
    """Snapshot an authoritative synchronous byte cursor, if available.

    The source contract forbids hidden consumption after read/seek returns or
    raises. An async tell coroutine is closed without running its body; it cannot
    provide the synchronous checkpoint needed here.
    """
    try:
        tell = getattr(source, "tell", None)
        if tell is None:
            return None
        position = tell()
    except Exception:
        return None
    if type(position) is int:
        return position if position >= 0 else None
    if inspect.iscoroutine(position):
        position.close()
    return None


def _is_native_source(source: Any, method: str) -> bool:
    """Recognize aiofiles' supported binary delegates without bypassing overrides."""
    return type(source) in (AsyncBufferedIOBase, AsyncBufferedReader, AsyncFileIO) and (
        method not in vars(source)
    )


class _NativeSourceCall:
    """Own completion independently of the cancellable executor notification.

    A lock arbitrates native entry against cancellation before entry. Once entry
    wins, only the worker can publish completion, after its last source access.
    A notification Future is allocated only when cancellation/context exit needs
    settlement; successful reads use the ordinary executor await directly.
    """

    __slots__ = (
        "source",
        "method",
        "args",
        "track_position",
        "no_effect",
        "prevented",
        "_loop",
        "_lock",
        "_started",
        "_finished",
        "_result",
        "_error",
        "_waiter",
    )

    def __init__(
        self,
        source: Any,
        method: str,
        args: tuple[Any, ...],
        loop: asyncio.AbstractEventLoop,
        *,
        track_position: bool = True,
    ) -> None:
        self.source = source
        self.method = method
        self.args = args
        # Sink writes need settlement only, not no-effect position evidence.
        self.track_position = track_position
        self.no_effect = False
        self.prevented = False
        self._loop = loop
        self._lock = threading.Lock()
        self._started = False
        self._finished = False
        self._result: Any = None
        self._error: Optional[BaseException] = None
        self._waiter: Optional[asyncio.Future[None]] = None

    def __call__(self) -> Any:
        with self._lock:
            if self.prevented:
                return None  # The atomic entry guard forbids all source access.
            self._started = True
        try:
            before = _source_position(self.source) if self.track_position else None
            try:
                result = getattr(self.source, self.method)(*self.args)
            except BaseException:
                self.no_effect = (
                    before is not None and _source_position(self.source) == before
                )
                raise
        except BaseException as error:
            self._publish(error=error)
            raise
        self._publish(result=result)
        return result

    def _publish(
        self, *, result: Any = None, error: Optional[BaseException] = None
    ) -> None:
        # No source access is permitted after this publication boundary.
        with self._lock:
            self._result = result
            self._error = error
            self._finished = True
            waiter = self._waiter
        if waiter is not None:
            self._loop.call_soon_threadsafe(waiter.set_result, None)

    def completion(self, *, cancel_pending: bool = False) -> asyncio.Future[None]:
        """Return a private settlement signal, optionally preventing native entry."""
        with self._lock:
            if cancel_pending and not self._started:
                # This transition and worker entry share the same lock. A worker
                # scheduled later cannot pass its guard and touch the source.
                self.prevented = True
                self.no_effect = True
                self._finished = True
            if self._waiter is None:
                self._waiter = self._loop.create_future()
                if self._finished:
                    self._waiter.set_result(None)
            elif self.prevented and not self._waiter.done():
                self._waiter.set_result(None)
            return self._waiter

    def result(self) -> Any:
        """Retrieve the outcome only after authoritative settlement."""
        with self._lock:
            if not self._finished:
                raise RuntimeError("native source work has not settled")
            error, result = self._error, self._result
        if error is not None:
            raise error
        return result
