# 2.0.0a4 WP1 boolean-validation inventory

This note records the public configuration inventory before WP1 changes. It
does not treat ordinary boolean results such as `isatty()` or internal fixed
constants such as the inspection scanner's `collect_members` choice as public
configuration.

| Parameter | Public surfaces | Pre-change behavior | Intended `a4` behavior |
| --- | --- | --- | --- |
| `fast_compress` | `AsyncGzipBinaryFile`, `AsyncGzipTextFile`, binary/text `AsyncGzipFile`, binary/text `open`, `write`, `compress_chunks`, `GzipEncoder` | Constructors/codecs used `bool(value)`; streaming warning selection also tested raw truthiness | Exact `bool` at every boundary, before warnings, engines, resources, or source iteration |
| `strict_size` | `AsyncGzipBinaryFile`, `AsyncGzipTextFile`, binary/text `AsyncGzipFile`, binary/text `open`, `write`, `compress_chunks`, `GzipEncoder` | Constructors/codecs used `bool(value)` | Exact `bool` in every mode, before resources, engines, or source iteration |
| `collect_member_info` | `GzipDecoder` | Constructor used `bool(value)` | Exact `bool` before decoder state construction |
| `closefd` | `AsyncGzipBinaryFile`, `AsyncGzipTextFile`, binary/text `AsyncGzipFile`, binary/text `open`, `read`, `write`, `inspect`, `verify` | File wrappers retained a non-`None` raw value and later relied on truthiness; inspection called `bool(value)` | `None` or exact `bool`, validated before any source or destination is acquired |

The factory and whole-file helper rows are intentional public surfaces even
though they delegate to the binary/text constructors. Tests exercise the
delegating surface so later wrapper changes cannot move validation after an
await or resource acquisition.

The private inspection scanner's `collect_members=True/False` values are
internal policy constants, not another public occurrence of
`collect_member_info`. Boolean-returning state queries and normal conversions
of results to booleans are likewise outside WP1. No such code is changed.
