"""Integration coverage for the maintained fragmented-transport example."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import aiogzip

REPO_ROOT = Path(__file__).parents[2]
EXAMPLE_PATH = REPO_ROOT / "examples" / "fragmented_transport.py"


def _load_example():
    spec = importlib.util.spec_from_file_location(
        "aiogzip_example_fragmented_transport",
        EXAMPLE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


example = _load_example()


def _reports_for_valid_fragmentations(wire):
    filename_split = 13
    trailer_start = len(wire) - 8
    frame_sets = [
        [wire, b""],
        [*example.fragment_bytes(wire, (1,)), b""],
        [*example.fragment_bytes(wire, example._FRAGMENT_PATTERN), b""],
        [*example.fragment_bytes(wire, example.deterministic_random_pattern()), b""],
        [wire[:trailer_start], wire[trailer_start:], b""],
        [
            wire[: trailer_start - 1],
            wire[trailer_start - 1 : trailer_start],
            wire[trailer_start:],
            b"",
        ],
        [
            wire[:filename_split],
            wire[filename_split : filename_split + 1],
            wire[filename_split + 1 :],
            b"",
        ],
    ]
    return [example.decode_frames(frames) for frames in frame_sets]


async def test_loopback_exposes_provisional_records_then_verifies():
    records = example.demo_records()

    report = await example.run_loopback(records)

    assert report.provisional_before_finish
    assert report.receive.status == "verified"
    assert report.receive.records == tuple(records)
    assert report.receive.decoded_sha256 == report.source_sha256
    assert report.receive.member_count == 1


def test_valid_frame_boundaries_are_invariant_and_empty_frame_is_protocol_only(
    monkeypatch,
):
    records = example.demo_records()
    wire, payload = example.encode_records(records)
    feed_sizes = []
    original_feed = aiogzip.GzipDecoder.feed

    def recording_feed(decoder, frame):
        feed_sizes.append(len(frame))
        return original_feed(decoder, frame)

    monkeypatch.setattr(aiogzip.GzipDecoder, "feed", recording_feed)

    reports = _reports_for_valid_fragmentations(wire)

    assert all(report.status == "verified" for report in reports)
    assert all(report.records == tuple(records) for report in reports)
    assert all(report.decoded_sha256 == reports[0].decoded_sha256 for report in reports)
    assert all(report.member_count == 1 for report in reports)
    assert all(feed_sizes)
    assert 0 not in feed_sizes
    assert example.gzip.decompress(wire) == payload


def test_concatenated_member_boundary_is_fragmentation_invariant():
    records = example.demo_records()
    first, _ = example.encode_records(records[:6])
    second, _ = example.encode_records(records[6:])
    frames = [
        first[:-1],
        first[-1:],
        second[:1],
        *example.fragment_bytes(second[1:], (1, 97, 3, 55)),
        b"",
    ]

    report = example.decode_frames(frames)

    assert report.status == "verified"
    assert report.records == tuple(records)
    assert report.member_count == 2


@pytest.mark.parametrize(
    ("damage", "expected_text"),
    [
        ("truncated", "truncated trailer"),
        ("crc", "CRC check failed"),
        ("isize", "ISIZE check failed"),
    ],
)
def test_trailer_failures_remain_invalid_after_provisional_output(
    damage, expected_text
):
    records = example.demo_records()
    wire, _ = example.encode_records(records)
    if damage == "truncated":
        damaged = wire[:-3]
    else:
        mutable = bytearray(wire)
        mutable[-8 if damage == "crc" else -4] ^= 1
        damaged = bytes(mutable)

    report = example.decode_frames([*example.fragment_bytes(damaged, (1, 97, 5)), b""])

    assert report.records
    assert report.status == "invalid"
    assert report.status != "verified"
    assert expected_text in report.error


def test_transport_eof_is_aborted_not_verified():
    wire, _ = example.encode_records(example.demo_records())

    report = example.decode_frames(example.fragment_bytes(wire, (7, 11)))

    assert report.status == "aborted"
    assert "transport EOF" in report.error


def test_early_abandonment_and_retained_invalidation_are_explicit():
    wire, _ = example.encode_records(example.demo_records())

    example.demonstrate_abandonment(wire)


@pytest.mark.parametrize("argument", ["--help", "--self-test"])
def test_cli_modes_exit_successfully(argument):
    result = subprocess.run(
        [sys.executable, str(EXAMPLE_PATH), argument],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    if argument == "--self-test":
        assert result.stdout == "fragmented transport self-test: passed\n"
    else:
        assert "framed loopback" in result.stdout


def test_example_uses_only_public_aiogzip_imports():
    source = EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "src.aiogzip" not in source
    assert "aiogzip._" not in source
