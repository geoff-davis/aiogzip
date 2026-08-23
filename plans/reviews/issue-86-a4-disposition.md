# Issue #86: 2.0 tiny-write disposition

Date: 2026-08-22

Candidate: `ed0fe742be1a7d9efbb670cf8cf1ac76d7090de8`

Baseline: `v2.0.0a3` at
`3e95073581be7cba437da45dacd9724f649e54d0`

## Diagnostic result

The authoritative diagnostic is the CPU-pinned, 21-sample write matrix. A
negative delta is faster. All output lengths and SHA-256 digests match.

| Engine | Method for 10-byte records | a3 median | a4 median | Delta |
| --- | --- | ---: | ---: | ---: |
| forced stdlib | `write()` per record | 0.816148 s | 0.772215 s | -5.38% |
| forced stdlib | `writelines()` | 0.098257 s | 0.091591 s | -6.78% |
| forced stdlib | explicit 64 KiB batches | 0.011598 s | 0.010475 s | -9.68% |
| forced stdlib | explicit 256 KiB batches | 0.011842 s | 0.011552 s | -2.44% |
| zlib-ng | `write()` per record | 0.778639 s | 0.781475 s | +0.36% |
| zlib-ng | `writelines()` | 0.088233 s | 0.083213 s | -5.69% |
| zlib-ng | explicit 64 KiB batches | 0.001321 s | 0.001307 s | -1.01% |
| zlib-ng | explicit 256 KiB batches | 0.002623 s | 0.002512 s | -4.20% |

Raw records:

- `plans/benchmarks/data/v2.0.0a3-a4-candidate-pinned-stdlib.json`
- `plans/benchmarks/data/v2.0.0a4-candidate-pinned-stdlib.json`
- `plans/benchmarks/data/v2.0.0a3-a4-candidate-pinned-zlib-ng.json`
- `plans/benchmarks/data/v2.0.0a4-candidate-pinned-zlib-ng.json`

The a4 anti-regression gate passes: the extreme per-call row is 5.38% faster
with forced stdlib and 0.36% slower with zlib-ng, both inside the 10% blocker.
These figures demonstrate preservation, not a promised improvement.

## Retained contract

One `await write(data)` retains the 2.0 same-call contract:

- the input is snapshotted immutably;
- that call's codec operation is completed;
- every compressed byte produced by that operation reaches the sink before
  return;
- logical position advances only after successful sink writes;
- a sink failure is raised by the call that triggered it; and
- failure or cancellation poisons the writer, so no valid-looking trailer can
  be appended to an incomplete member.

Default cross-call buffering would move visibility and sink errors from one
public call to a later call, `flush()`, or `close()`. It would also require a
new buffer limit, failure attribution, cancellation, close, and memory
contract. That is a distinct buffered-writer feature, not a transparent
optimization of `write()`.

For 2.0, callers should use `writelines()` when records are already available
as a synchronous iterable, or construct explicit bounded batches when the
application owns an asynchronous source. Both preserve bounded memory while
amortizing coroutine and codec-operation overhead.

## Recommendation

Close #86 as accepted for the 2.0 strict-semantics design. If demand remains,
reframe follow-up work as an explicit, opt-in buffered-writer API with its own
visibility, failure-timing, cancellation, flush, close, and memory contract.
Do not change default `write()` semantics during 2.0 stabilization.

Codex did not comment on, label, close, or otherwise modify the remote issue.
