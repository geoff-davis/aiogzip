# 2.0.0a4 WP2 completed-member metadata characterization

The pre-change decoder was exercised with one complete, trailer-validated
member followed by a second member whose CRC was corrupt.

| Observation | Value |
| --- | --- |
| Before member 1 failure | `member_count=1`, `len(members)=1`, `finished=False` |
| Failure | `gzip.BadGzipFile: CRC check failed in gzip member 1` |
| After failure | `member_count=1`, `len(members)=0`, `finished=False` |
| Later codec call | `OSError: gzip decoder is unusable after a prior failure` |

The inconsistency came from `GzipDecoder._release_state()` clearing
`_members` while deliberately preserving `_member_count` and cumulative
accounting. Completed `GzipMemberInfo` values are frozen snapshots appended
only after CRC and ISIZE trailer validation; they do not reference the mutable
parser, engine, pending input, or output cursor.

WP2 therefore removes only `_members.clear()` from the ordinary failure and
discard release path. It retains the existing release of pending spans,
inflate input, pending output, delayed EOF state, engine, active header, and
header parser, and resets incomplete per-member CRC, size, offset, and phase
state. It does not add reset/reuse behavior or a second metadata path. The
decoder remains permanently unusable after failure, operation abandonment, or
explicit discard, and `finished` continues to mean that the complete
concatenated stream validated successfully.
