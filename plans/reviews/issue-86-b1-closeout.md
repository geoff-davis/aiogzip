# Issue #86: 2.0.0b1 closeout packet

Date observed: 2026-08-31

Issue: [#86](https://github.com/geoff-davis/aiogzip/issues/86), “2.0:
small-write overhead vs v1.11.0 (deferred from 2.0.0a2)”

## Observed remote state

- State: open.
- State reason: unset.
- Comments: none.
- Labels and milestone: none.
- The original body remains intact and describes the historical v1.11.0
  comparison and the 10% anti-regression gate.

Codex performed no remote mutation.

## Evidence

- Accepted a4 design disposition:
  `plans/reviews/issue-86-a4-disposition.md`.
- Forced-stdlib raw write matrix:
  `plans/benchmarks/data/v2.0.0a4-candidate-pinned-stdlib.json`.
- zlib-ng raw write matrix:
  `plans/benchmarks/data/v2.0.0a4-candidate-pinned-zlib-ng.json`.

The controlled a3 to a4 10-byte-per-call diagnostic was 5.38% faster with
forced stdlib zlib and 0.36% slower with zlib-ng. Both passed the retained 10%
anti-regression gate. The b1 candidate must again pass the exact-a4 gate before
the maintainer uses this packet.

## Exact proposed maintainer comment

```markdown
The 2.0 tiny-write investigation is complete.

`v2.0.0a4` preserved the strict same-call `write()` contract: each call snapshots its input, completes its codec operation, delivers every compressed byte produced by that operation to the sink before returning, attributes sink failures to the triggering call, and poisons the writer after failure or cancellation.

Default buffering across separate `write()` calls would change output visibility, sink-error timing, cancellation behavior, flush/close semantics, and memory limits. It is therefore a separate API design rather than a transparent optimization.

The controlled `a3` → `a4` benchmark showed the 10-byte-per-call diagnostic 5.38% faster with forced stdlib zlib and 0.36% slower with zlib-ng. Both pass the retained anti-regression gate. For workloads containing many tiny records, use `writelines()` or explicit bounded application-level batching.

We are accepting this overhead for the 2.0 strict-semantics design and will not change default `write()` behavior during 2.0 stabilization. A future opt-in buffered-writer API can be considered separately if concrete user demand justifies defining its visibility, failure-timing, cancellation, flush, close, and memory contracts.
```

## Maintainer-only actions

- [ ] Confirm the final b1 tiny-write row remains within the 10% exact-a4 gate.
- [ ] Confirm no equivalent closeout comment has appeared since this packet was
  captured. If one exists, record its URL and do not duplicate it.
- [ ] Leave the original issue title and body unchanged.
- [ ] Post the exact approved comment above.
- [ ] Close #86 as **Not planned**, or the repository's equivalent
  accepted-design-tradeoff resolution—not Completed.
- [ ] Record the comment URL, closure state/reason, and timestamp in final
  release evidence.

Do not retarget #86. Do not open a separate buffered-writer issue without
concrete user demand or a separately developed and reviewed API proposal.
Issue closure does not remove the continuing tiny-write anti-regression row.
