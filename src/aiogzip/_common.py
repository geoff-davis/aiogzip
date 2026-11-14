"""Shared constants, helpers, and protocols for aiogzip internals."""

import os
import re
import struct
import time
from typing import (
    Any,
    Optional,
    Protocol,
    Tuple,
    Union,
    runtime_checkable,
)

# Constants
# The wbits parameter for zlib that enables gzip format
# 31 = 16 (gzip format) + 15 (maximum window size)
GZIP_WBITS = 31

# gzip header constants
GZIP_FLAG_FNAME = 0x08
GZIP_FLAG_FHCRC = 0x02
GZIP_FLAG_FEXTRA = 0x04
GZIP_FLAG_FCOMMENT = 0x10
GZIP_METHOD_DEFLATE = 8
GZIP_OS_UNKNOWN = 255
_COMPRESS_LEVEL_FAST = 1
_COMPRESS_LEVEL_BEST = 9
_MAX_GZIP_MTIME = 0xFFFFFFFF

# Every public ``filename`` parameter. The runtime check in
# ``_validate_filename`` accepts any ``os.PathLike``, so the annotation does
# too; ``pathlib.Path`` is an ``os.PathLike[str]``.
_Filename = Union[str, bytes, os.PathLike[str], os.PathLike[bytes], None]

# Safety cap for chunk_size and peek() arguments (128 MiB). Prevents a caller
# from accidentally allocating gigabytes when passing an unsanitized integer
# from user input. It is also the default max_rewind_cache_size. read(size) and
# readinto() are not capped: readinto() keeps filling the internal buffer
# until at least len(b) bytes are available (the last fill can overshoot) and
# only then copies, so a failed refill leaves the stream intact.
_MAX_CHUNK_SIZE = 128 * 1024 * 1024

# Type alias for zlib compression/decompression objects
# These are the return types of zlib.compressobj() and zlib.decompressobj()
# The actual types (zlib.Compress/zlib.Decompress) are C extension types that
# aren't exposed in the type stubs, so we use Any at runtime and for type checking
ZlibEngine = Any


# Validation helper functions
def _validate_bool(value: object, name: str) -> bool:
    """Return an exact bool or raise a parameter-specific TypeError."""
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")
    return value


def _validate_optional_bool(value: object, name: str) -> bool | None:
    """Return None or an exact bool."""
    if value is None:
        return None
    return _validate_bool(value, name)


def _check_can_open(is_closed: bool, is_open: bool) -> None:
    """Validate the open() precondition shared by the binary and text classes.

    Raises:
        ValueError: If the file is already open, or has been closed (a closed
            instance cannot be reopened, matching io objects).
    """
    if is_closed:
        raise ValueError("Cannot reopen a closed file")
    if is_open:
        raise ValueError("File is already open")


def _format_file_repr(obj: Any) -> str:
    """Shared __repr__ for the file classes: name, mode, and closed state.

    Tolerates partially-constructed instances: the classes use __slots__ and
    their __init__ can raise mid-validation, and debuggers / locals-capturing
    traceback formatters call repr() on such half-built objects.
    """
    cls_name = type(obj).__name__
    try:
        closed = obj.closed
        # The binary class holds its file in _file, the text class its binary
        # handle in _binary_file. ``closed`` is False before open() as well,
        # so say which of the two states this is.
        opened = (
            getattr(obj, "_binary_file", None) is not None
            or getattr(obj, "_file", None) is not None
        )
        state = f"closed={closed}" if closed or opened else "unopened"
        return f"<aiogzip.{cls_name} name={obj.name!r} mode={obj._mode!r} {state}>"
    except AttributeError:
        return f"<aiogzip.{cls_name} [uninitialized]>"


def _validate_filename(filename: _Filename, fileobj: Any) -> None:
    """Validate filename parameter.

    Args:
        filename: The filename to validate
        fileobj: The fileobj parameter (for checking if at least one is provided)

    Raises:
        ValueError: If both filename and fileobj are None, or if filename is empty
        TypeError: If filename is not a string, bytes, or PathLike object
    """
    if filename is None and fileobj is None:
        raise ValueError("Either filename or fileobj must be provided")
    if filename is not None:
        if not isinstance(filename, (str, bytes, os.PathLike)):
            message = "Filename must be a string, bytes, or PathLike object"
            if _looks_like_file(filename):
                message += (
                    f", not {type(filename).__name__}; pass a file object as "
                    "fileobj=..."
                )
            raise TypeError(message)
        if isinstance(filename, str) and not filename:
            raise ValueError("Filename cannot be empty")


# CPython 3.14 says "'bytes' object can't be awaited"; earlier versions say
# "object bytes can't be used in 'await' expression".
_NOT_AWAITABLE = re.compile(
    r"'([\w.]+)' object can't be awaited"
    r"|object ([\w.]+) can't be used in 'await' expression"
)


def _sync_fileobj_message(error: BaseException, method: str) -> Optional[str]:
    """Explain an await of a synchronous file object's result, if that is it.

    ``isinstance(io.BytesIO(), WithAsyncRead)`` is true, because a runtime
    protocol checks names only, so a synchronous file object is found out
    when its first result is awaited. This runs in the handler that already
    holds that ``TypeError``; the read path makes no extra check.
    """
    if not isinstance(error, TypeError):
        return None
    # The text alone does not say where the await failed: an async read()
    # that awaits a non-awaitable internally raises the same error. Rewrite
    # only when the innermost frame is aiogzip's own await of the result.
    traceback = error.__traceback__
    if traceback is None:
        return None
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    module = traceback.tb_frame.f_globals.get("__name__")
    if not isinstance(module, str) or not module.startswith("aiogzip."):
        return None
    match = _NOT_AWAITABLE.search(str(error))
    if match is None:
        return None
    returned = match.group(1) or match.group(2)
    return (
        f"fileobj.{method}() returned {returned}, not an awaitable; aiogzip "
        "needs an async file object. Wrap a sync file with "
        "aiofiles.threadpool.wrap(f), or use gzip.open()."
    )


def _note_source(error: BaseException, name: object, action: str = "reading") -> None:
    """Name the file on ``error`` with a note, when a path-like name is known.

    The message is left alone: the sans-I/O codec that built it has no
    filename, and callers match on the message text. The note is best
    effort: a name whose ``__fspath__`` or ``__repr__`` raises must not
    replace the error being reported.
    """
    try:
        if isinstance(name, (str, bytes, os.PathLike)):
            error.add_note(f"while {action} {os.fspath(name)!r}")
    except Exception:
        pass


def _source_name(filename: object, fileobj: object) -> object:
    """Return the filename, or the file object's ``name``, without raising."""
    if filename is not None:
        return filename
    try:
        return getattr(fileobj, "name", None)
    except Exception:
        return None


def _looks_like_file(value: object) -> bool:
    """Report whether ``value`` has ``read`` or ``write``, without raising."""
    try:
        return hasattr(value, "read") or hasattr(value, "write")
    except Exception:
        return False


def _validate_chunk_size(chunk_size: int) -> None:
    """Validate chunk_size parameter.

    Args:
        chunk_size: The chunk size to validate

    Raises:
        ValueError: If chunk size is invalid
    """
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool):
        raise TypeError("Chunk size must be an integer")
    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive")
    if chunk_size > _MAX_CHUNK_SIZE:
        raise ValueError(
            f"Chunk size must be <= {_MAX_CHUNK_SIZE} bytes "
            f"({_MAX_CHUNK_SIZE // (1024 * 1024)} MiB)"
        )


def _validate_compresslevel(compresslevel: int) -> None:
    """Validate compresslevel parameter.

    Args:
        compresslevel: The compression level to validate

    Raises:
        ValueError: If compression level is not between -1 and 9
    """
    if not isinstance(compresslevel, int) or isinstance(compresslevel, bool):
        raise TypeError("Compression level must be an integer")
    if not (-1 <= compresslevel <= 9):
        raise ValueError("Compression level must be between -1 and 9")


def _validate_optional_positive_int(value: Optional[int], name: str) -> None:
    """Validate an optional byte-count limit shared by both stream classes."""
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be a positive integer or None")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _normalize_mtime(mtime: Optional[Union[int, float]]) -> Optional[int]:
    """Validate and normalize mtime values."""
    if mtime is None:
        return None
    if isinstance(mtime, bool) or not isinstance(mtime, (int, float)):
        raise TypeError("mtime must be an int or float if provided")
    if mtime != mtime or mtime in (float("inf"), float("-inf")):
        raise ValueError("mtime must be a finite number")
    if mtime < 0:
        raise ValueError("mtime must be non-negative")
    normalized = int(mtime)
    if normalized > _MAX_GZIP_MTIME:
        raise ValueError(f"mtime must be <= {_MAX_GZIP_MTIME}")
    return normalized


def _validate_original_filename(
    filename: Optional[Union[str, bytes]],
) -> Optional[Union[str, bytes]]:
    """Validate optional original filename parameter."""
    if filename is None:
        return filename
    if isinstance(filename, bytes):
        if b"\x00" in filename:
            raise ValueError("original_filename cannot contain NUL bytes")
        return filename
    if isinstance(filename, str):
        if "\x00" in filename:
            raise ValueError("original_filename cannot contain NUL bytes")
        return filename
    raise TypeError("original_filename must be a string or bytes if provided")


def _derive_header_filename(
    explicit: Optional[Union[str, bytes]],
    fallback: Union[str, bytes, os.PathLike, None],
) -> bytes:
    """Derive the filename stored in the gzip header."""
    candidate: Union[str, bytes, os.PathLike, None] = (
        explicit if explicit is not None else fallback
    )
    if candidate is None:
        return b""

    if isinstance(candidate, os.PathLike):
        candidate = os.fspath(candidate)

    if isinstance(candidate, bytes):
        base_bytes = os.path.basename(candidate)
        if base_bytes.endswith(b".gz"):
            base_bytes = base_bytes[:-3]
        return base_bytes

    if isinstance(candidate, str):
        base_str = os.path.basename(candidate)
        if base_str.endswith(".gz"):
            base_str = base_str[:-3]
        try:
            return base_str.encode("latin-1")
        except UnicodeEncodeError:
            return b""

    raise TypeError("original_filename must be a string or bytes if provided")


def _build_gzip_header(
    filename_bytes: bytes, mtime: Optional[int], compresslevel: int
) -> bytes:
    """Construct a gzip header matching CPython's gzip implementation."""
    header = bytearray()
    header.extend(b"\x1f\x8b")
    header.append(GZIP_METHOD_DEFLATE)
    flags = GZIP_FLAG_FNAME if filename_bytes else 0
    header.append(flags)
    seconds = int(time.time()) if mtime is None else int(mtime)
    header.extend(struct.pack("<I", seconds))

    if compresslevel == _COMPRESS_LEVEL_BEST:
        xfl = 2
    elif compresslevel == _COMPRESS_LEVEL_FAST:
        xfl = 4
    else:
        xfl = 0
    header.append(xfl)
    header.append(GZIP_OS_UNKNOWN)

    if filename_bytes:
        header.extend(filename_bytes)
        header.append(0)

    return bytes(header)


def _build_gzip_trailer(crc: int, size: int) -> bytes:
    """Construct the gzip trailer (CRC32 + uncompressed size)."""
    return struct.pack("<II", crc & 0xFFFFFFFF, size & 0xFFFFFFFF)


def _parse_mode_tokens(mode: str) -> Tuple[str, bool, bool, bool]:
    """Parse a mode string into (op, saw_b, saw_t, plus) flags."""
    if not isinstance(mode, str):
        raise TypeError("mode must be a string")
    if not mode:
        raise ValueError("Mode string cannot be empty")

    op: Optional[str] = None
    saw_b = False
    saw_t = False
    plus = False

    for ch in mode:
        if ch in {"r", "w", "a", "x"}:
            if op is not None:
                raise ValueError("Mode string can only specify one of r, w, a, or x")
            op = ch
        elif ch == "b":
            if saw_b:
                raise ValueError("Mode string cannot specify 'b' more than once")
            saw_b = True
        elif ch == "t":
            if saw_t:
                raise ValueError("Mode string cannot specify 't' more than once")
            saw_t = True
        elif ch == "+":
            if plus:
                raise ValueError("Mode string cannot include '+' more than once")
            plus = True
        else:
            raise ValueError(f"Invalid mode character '{ch}'")

    if op is None:
        raise ValueError("Mode string must include one of 'r', 'w', 'a', or 'x'")
    if saw_b and saw_t:
        raise ValueError("Mode string cannot include both 'b' and 't'")

    return op, saw_b, saw_t, plus


@runtime_checkable
class WithAsyncRead(Protocol):
    """Protocol for async file-like objects that can be read."""

    async def read(self, size: int = -1) -> Union[str, bytes]: ...


@runtime_checkable
class WithAsyncWrite(Protocol):
    """Protocol for async file-like objects that can be written."""

    async def write(self, data: Union[str, bytes]) -> int: ...


@runtime_checkable
class WithAsyncReadWrite(Protocol):
    """Protocol for async file-like objects that can be read and written."""

    async def read(self, size: int = -1) -> Union[str, bytes]: ...
    async def write(self, data: Union[str, bytes]) -> int: ...
    async def close(self) -> None: ...


class _WithAsyncBinaryWrite(Protocol):
    """What a ``fileobj`` sink must provide; an input annotation only.

    A sink is only ever given ``bytes``, positionally, so a binary sink (an
    aiofiles ``"wb"`` handle, ``write(self, b: bytes)``) is accepted although
    it does not satisfy the public :class:`WithAsyncWrite`, whose ``write``
    also takes ``str`` and a ``data`` keyword. Every ``WithAsyncWrite`` and
    ``WithAsyncReadWrite`` satisfies this protocol.
    """

    async def write(self, data: bytes, /) -> int: ...


__all__ = [
    "GZIP_WBITS",
    "GZIP_FLAG_FNAME",
    "GZIP_FLAG_FHCRC",
    "GZIP_FLAG_FEXTRA",
    "GZIP_FLAG_FCOMMENT",
    "GZIP_METHOD_DEFLATE",
    "GZIP_OS_UNKNOWN",
    "ZlibEngine",
    "_validate_bool",
    "_validate_optional_bool",
    "_validate_filename",
    "_validate_chunk_size",
    "_validate_compresslevel",
    "_validate_optional_positive_int",
    "_normalize_mtime",
    "_validate_original_filename",
    "_derive_header_filename",
    "_build_gzip_header",
    "_build_gzip_trailer",
    "_parse_mode_tokens",
    "WithAsyncRead",
    "WithAsyncWrite",
    "WithAsyncReadWrite",
]
