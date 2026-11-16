"""Private implementation of the async-iterable source adapter.

The adapter is a plain byte source: it knows nothing about gzip. Framing,
member traversal and limits stay in ``codec.py``; the file handle reads the
adapter as it reads any other custom ``fileobj``.
"""

import asyncio
import inspect
from typing import Any, AsyncIterable, Optional, Union

# An item that is empty is skipped, not treated as end of input. A source
# that yields empty items without suspending would otherwise hold the event
# loop inside one read(), so the adapter yields after this many in a row.
_EMPTY_ITEMS_CHECKPOINT = 256


class IterableReader:
    """Present an asynchronous iterable of bytes as a readable ``fileobj``.

    Pass an instance as ``fileobj`` to :func:`aiogzip.open` to read lines,
    text or sized binary reads from a source that offers only async
    iteration, such as an HTTP response body or an object-store download::

        reader = aiogzip.IterableReader(response.aiter_raw())
        async with aiogzip.open(None, "rt", fileobj=reader, closefd=True) as f:
            async for line in f:
                ...

    Items may be ``bytes``, ``bytearray`` or ``memoryview``. Empty items are
    skipped. The source is consumed one item at a time, only when a read
    needs more input, so it is never read ahead.

    The reader cannot seek. A gzip handle reading from it rewinds through its
    rewind cache, which ``max_rewind_cache_size`` bounds.

    If the source raises, or a read is cancelled while waiting for the next
    item, the reader becomes unusable: it cannot know whether the source
    consumed input, so later reads raise ``OSError`` and :meth:`tell` raises
    ``ValueError``. A gzip handle reading from it then reports its stream as
    broken, as for any custom source in that state.

    A reader serves one consumer. It is not safe to share between tasks.
    """

    __slots__ = (
        "_cleaned_up",
        "_closed",
        "_eof",
        "_failure",
        "_head",
        "_iterator",
        "_offset",
        "_position",
        "_reading",
        "_source",
    )

    def __init__(
        self, source: AsyncIterable[Union[bytes, bytearray, memoryview]]
    ) -> None:
        if not callable(getattr(source, "__aiter__", None)):
            hint = ""
            if isinstance(source, (bytes, bytearray, memoryview)):
                hint = "; to decompress bytes in memory use aiogzip.decompress()"
            elif callable(getattr(source, "__iter__", None)):
                hint = "; a synchronous iterable is not accepted"
            raise TypeError(
                "source must be an asynchronous iterable of bytes, "
                f"not {type(source).__name__}{hint}"
            )
        self._source: Any = source
        self._iterator: Any = None
        self._head = b""
        self._offset = 0
        self._position = 0
        self._eof = False
        self._closed = False
        self._cleaned_up = False
        self._reading = False
        self._failure: Optional[BaseException] = None

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        return self._closed

    def tell(self) -> int:
        """Return the number of bytes handed out by :meth:`read` so far.

        Raises:
            ValueError: If the reader is closed, or unusable after its source
                failed or a read was cancelled.
        """
        if self._closed:
            raise ValueError("I/O operation on closed reader")
        if self._failure is not None:
            raise ValueError("reader is unusable after its source failed")
        return self._position

    async def read(self, size: Optional[int] = -1) -> bytes:
        """Read up to ``size`` bytes.

        A positive ``size`` returns between 1 and ``size`` bytes: whatever is
        left of the current source item, without waiting for another one. It
        returns ``b""`` only at the end of the source. ``size`` of ``None``
        or a negative number reads to the end of the source.

        Raises:
            TypeError: If ``size`` is not an integer or ``None``, or a source
                item is not ``bytes``, ``bytearray`` or ``memoryview``.
            ValueError: If the reader is closed.
            OSError: If the reader is unusable after an earlier failure.
            RuntimeError: If another read is already in progress.
        """
        if size is None:
            size = -1
        elif type(size) is not int:
            raise TypeError(f"size must be an int or None, not {type(size).__name__}")
        if self._closed:
            raise ValueError("I/O operation on closed reader")
        if self._failure is not None:
            raise OSError(
                "reader is unusable after its source failed"
            ) from self._failure
        if self._reading:
            raise RuntimeError("IterableReader.read() is already in progress")
        if size == 0:
            return b""
        self._reading = True
        try:
            if size > 0:
                return await self._read_some(size)
            parts = []
            while chunk := await self._read_some(-1):
                parts.append(chunk)
            return b"".join(parts)
        finally:
            self._reading = False

    async def _read_some(self, size: int) -> bytes:
        """Return the rest of the current item, or up to ``size`` bytes of it."""
        head = self._head
        offset = self._offset
        if offset >= len(head):
            head = await self._next_item()
            offset = 0
            if not head:
                return b""
        available = len(head) - offset
        if size < 0 or size >= available:
            chunk = head if offset == 0 else head[offset:]
            self._head = b""
            self._offset = 0
        else:
            chunk = head[offset : offset + size]
            self._head = head
            self._offset = offset + size
        self._position += len(chunk)
        return chunk

    async def _next_item(self) -> bytes:
        """Pull the next non-empty item; ``b""`` means the source has ended."""
        if self._eof:
            return b""
        empty_items = 0
        try:
            if self._iterator is None:
                iterator = self._source.__aiter__()
                if not callable(getattr(iterator, "__anext__", None)):
                    raise TypeError(
                        "source.__aiter__() must return an asynchronous iterator"
                    )
                self._iterator = iterator
            while True:
                try:
                    item = await self._iterator.__anext__()
                except StopAsyncIteration:
                    self._eof = True
                    return b""
                if type(item) is not bytes:
                    if isinstance(item, bytes):
                        # Copy a subclass's raw storage without calling its
                        # overrides.
                        item = bytes.__getitem__(item, slice(None))
                    elif isinstance(item, (bytearray, memoryview)):
                        item = memoryview(item).tobytes()
                    else:
                        raise TypeError(
                            "IterableReader source items must be bytes, "
                            f"bytearray or memoryview, not {type(item).__name__}"
                        )
                if item:
                    return item
                empty_items += 1
                if empty_items >= _EMPTY_ITEMS_CHECKPOINT:
                    empty_items = 0
                    await asyncio.sleep(0)
        except BaseException as failure:
            # The source may have consumed input that was never returned, and
            # a generator cancelled mid-step cannot be resumed.
            self._failure = failure
            raise

    async def close(self) -> None:
        """Close the reader and the source iterator.

        Calls the iterator's ``aclose()`` when it has one, so an async
        generator's cleanup runs. If iteration never started, an ``aclose()``
        on the source itself is used. Closing again after a close that
        succeeded has no effect. If the source's ``aclose()`` raises or is
        cancelled, the reader stays closed to reads, the error propagates and
        a later ``close()`` calls ``aclose()`` again.
        """
        if self._cleaned_up:
            return
        self._closed = True
        self._head = b""
        self._offset = 0
        # Keep the source until its cleanup has succeeded, so that a failed
        # or cancelled close can be retried.
        target = self._iterator if self._iterator is not None else self._source
        aclose = getattr(target, "aclose", None)
        if callable(aclose):
            result = aclose()
            if inspect.isawaitable(result):
                await result
        self._cleaned_up = True
        self._iterator = None
        self._source = None

    async def aclose(self) -> None:
        """Alias of :meth:`close`, for code written against async generators."""
        await self.close()

    def __repr__(self) -> str:
        if self._closed:
            state = "closed"
        elif self._failure is not None:
            state = "failed"
        else:
            state = f"position={self._position}"
        return f"<aiogzip.IterableReader {state}>"
