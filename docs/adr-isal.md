# ADR: ISA-L (python-isal) evaluated, not adopted

**Status:** Decided (1.11.0) — not adopted. Revisit criteria below.

## Context

[python-isal](https://github.com/pycompression/python-isal) binds Intel's
ISA-L library, which advertises substantially faster DEFLATE than zlib. aiogzip
already ships an optional fast engine (zlib-ng via the `[fast]` extra), so the
question was whether isal should be added as a second — or replacement —
engine for decompression and/or compression.

## Decision

Not adopted. zlib-ng remains the only optional engine.

## Key findings

- **Correctness is not the issue.** isal's decompressed output is
  byte-identical to zlib's, as gzip requires.
- **ARM is a clear loss.** On macOS arm64 and Linux aarch64, isal was
  dominated by zlib-ng in every measured cell. The macOS arm64 wheel of
  isal 1.8.0 decompressed at plain-C speeds (~0.45 GB/s vs 2.4 GB/s for the
  comparable manylinux aarch64 wheel) and appears to be built without the
  optimized assembly;
  [python-isal#254](https://github.com/pycompression/python-isal/issues/254)
  reports this upstream with symbol-level evidence.
- **x86-64 Linux is a narrow, conditional win.** isal beat zlib-ng by about
  1.4x on realistic-entropy data (~5x compression ratio) but lost on
  high-ratio data. Benchmark fixtures with extreme compression ratios mostly
  measure output copying rather than DEFLATE decode, and overstate engines
  that optimize the copy path — a trap this evaluation had to correct for.
- **Compression is capped at levels 0–3.** isal cannot express the default
  gzip level 6, so it could at most back an opt-in "fast compression" mode —
  a role zlib-ng already fills with full level support.
- **An implementation hazard.** aiogzip's incremental decoder currently relies
  on zlib's post-EOF behavior of aliasing leftover bytes into both
  `unused_data` and `unconsumed_tail`. isal does not share that quirk, so
  adopting it safely requires rewriting consumption accounting to count bytes
  arithmetically instead of trusting post-EOF engine attributes — planned as
  part of the 2.0 sans-IO extraction, not a minor-release change.

## Revisit when

- isal shows a decisive x86-64 decompression win over zlib-ng on
  realistic-entropy data (not extreme-ratio fixtures), or
- the engine-agnostic consumption-accounting rewrite lands (2.0 sans-IO
  extraction), removing the main implementation hazard.
