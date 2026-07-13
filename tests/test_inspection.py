"""Tests for gzip stream inspection contracts and behavior."""

from dataclasses import FrozenInstanceError

import pytest

from aiogzip import GzipInfo, GzipMemberInfo, VerificationResult


def _member() -> GzipMemberInfo:
    return GzipMemberInfo(
        index=0,
        compressed_offset=0,
        compressed_size=25,
        uncompressed_size=5,
        mtime=0,
        original_filename="data.bin",
        comment=None,
        extra=None,
        flags=8,
        crc32=0x3610A686,
        trailer_isize=5,
    )


def test_gzip_info_member_count():
    member = _member()
    info = GzipInfo(members=(member,), compressed_size=25, uncompressed_size=5)

    assert info.member_count == 1
    assert info.members == (member,)


def test_empty_gzip_info_contract():
    info = GzipInfo(members=(), compressed_size=0, uncompressed_size=0)

    assert info.member_count == 0


@pytest.mark.parametrize(
    "value",
    [
        _member(),
        GzipInfo(members=(_member(),), compressed_size=25, uncompressed_size=5),
        VerificationResult(member_count=1, compressed_size=25, uncompressed_size=5),
    ],
)
def test_result_types_are_immutable(value):
    with pytest.raises(FrozenInstanceError):
        value.compressed_size = 0
