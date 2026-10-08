"""Whether this platform reproduces the wires the recorded traces assume.

The recorded C0 and b1 traces (``tests/data/wp10_c0_traces.json`` and
``tests/data/wp10_b1_runs.json``), and the wire offsets that
``test_differential.py`` pins, hold only for the exact bytes they were
recorded from. The generator builds every member with ``gzip.compress()``,
whose DEFLATE stream depends on the platform's zlib: a zlib-ng-backed stdlib
(the Windows Python 3.14 CI leg) emits different streams. ``REPRODUCED``
compares one SHA-256 over every member the generator compresses for the
recorded seeds and the seeds that test pins directly with the value from
zlib.

The header's OS byte is excluded: Python 3.13 changed it from zlib's value
(3 on Unix) to 255, so it varies with the Python version while the replays,
which pass on every supported version, do not depend on it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import generator

DATA = Path(__file__).resolve().parent.parent / "data"

# Seeds test_differential.py passes to generate() directly; several of them
# are not recorded but have pinned wire offsets (seed 129's H-test bounds).
PINNED_SEEDS = frozenset(
    {4, 20, 62, 124, 129, 164, 169, 290, 316, 499, 558, 584, 1404, 1755, 2060}
    | {2512, 2969, 3525, 4819}
)

# The gzip header byte that names the OS; see the module docstring.
OS_BYTE = 9

WIRES_SHA256 = "014daf1f6e2433b3516a2ffde679ce8d4509413532914980ac11df25c8697f22"


def recorded_seeds() -> set[int]:
    c0 = json.loads((DATA / "wp10_c0_traces.json").read_text(encoding="utf-8"))
    b1 = json.loads((DATA / "wp10_b1_runs.json").read_text(encoding="utf-8"))
    return {int(seed) for seed in c0["traces"]} | {int(seed) for seed in b1["runs"]}


def wires_digest() -> str:
    """SHA-256 over the members and final wires of the recorded and pinned seeds.

    Each scenario is generated from OS-byte-normalized members, so the final
    wire (with its corruption, truncation and padding) is hashed as it is
    built on Python 3.13 and newer, whatever the running version.
    """
    digest = hashlib.sha256()
    compress = generator._member

    def normalized(rng, payload):
        member = compress(rng, payload)
        member = member[:OS_BYTE] + b"\xff" + member[OS_BYTE + 1 :]
        digest.update(b"member %d:" % len(member))
        digest.update(member)
        return member

    generator._member = normalized
    try:
        for seed in sorted(recorded_seeds() | PINNED_SEEDS):
            scenario = generator.generate(seed)
            wire = generator.unb64(scenario["wire"]) if "wire" in scenario else b""
            digest.update(b"seed %d wire %d:" % (seed, len(wire)))
            digest.update(wire)
    finally:
        generator._member = compress
    return digest.hexdigest()


REPRODUCED = wires_digest() == WIRES_SHA256
