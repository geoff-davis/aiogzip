"""Whether this platform reproduces the wires the recorded traces assume.

The recorded C0 and b1 traces (``tests/data/wp10_c0_traces.json`` and
``tests/data/wp10_b1_runs.json``), and the wire offsets that
``test_differential.py`` pins, hold only for the exact bytes they were
recorded from. The generator builds every wire with ``gzip.compress()``,
whose output depends on the platform's zlib: a zlib-ng-backed stdlib (the
Windows Python 3.14 CI leg) emits different streams. ``REPRODUCED`` compares
one SHA-256 over the generated wire of every recorded seed and of every seed
that test pins directly with the value from zlib.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from generator import generate, unb64

DATA = Path(__file__).resolve().parent.parent / "data"

# Seeds test_differential.py passes to generate() directly; several of them
# are not recorded but have pinned wire offsets (seed 129's H-test bounds).
PINNED_SEEDS = frozenset(
    {4, 20, 62, 124, 129, 164, 169, 290, 316, 499, 558, 584, 1404, 1755, 2060}
    | {2512, 2969, 3525, 4819}
)

WIRES_SHA256 = "f5ff0056843cf57c36d75826d63ae227c70a3ab6770581b50a55b98c9253491f"


def recorded_seeds() -> set[int]:
    c0 = json.loads((DATA / "wp10_c0_traces.json").read_text(encoding="utf-8"))
    b1 = json.loads((DATA / "wp10_b1_runs.json").read_text(encoding="utf-8"))
    return {int(seed) for seed in c0["traces"]} | {int(seed) for seed in b1["runs"]}


def wires_digest() -> str:
    """SHA-256 over the generated wire of every recorded and pinned seed."""
    digest = hashlib.sha256()
    for seed in sorted(recorded_seeds() | PINNED_SEEDS):
        scenario = generate(seed)
        if "wire" in scenario:
            digest.update(b"%d:" % seed)
            digest.update(unb64(scenario["wire"]))
    return digest.hexdigest()


REPRODUCED = wires_digest() == WIRES_SHA256
