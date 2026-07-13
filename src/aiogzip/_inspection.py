"""Gzip stream inspection result types and private scanner internals."""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class GzipMemberInfo:
    """Validated metadata and sizes for one gzip member.

    ``mtime`` preserves the literal unsigned header value, including zero.
    Filename and comment fields are decoded one-to-one with Latin-1; absent
    fields are ``None``, while present empty fields are empty strings.
    """

    index: int
    compressed_offset: int
    compressed_size: int
    uncompressed_size: int
    mtime: Optional[int]
    original_filename: Optional[str]
    comment: Optional[str]
    extra: Optional[bytes]
    flags: int
    crc32: int
    trailer_isize: int


@dataclass(frozen=True)
class GzipInfo:
    """Aggregate information for a completely validated gzip stream."""

    members: Tuple[GzipMemberInfo, ...]
    compressed_size: int
    uncompressed_size: int

    @property
    def member_count(self) -> int:
        """Return the number of gzip members in stream order."""
        return len(self.members)


@dataclass(frozen=True)
class VerificationResult:
    """Aggregate counts returned after successful integrity verification."""

    member_count: int
    compressed_size: int
    uncompressed_size: int
