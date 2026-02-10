# API Reference

`aiogzip` exposes its supported public API from the top-level package:

- `AsyncGzipBinaryFile`
- `AsyncGzipTextFile`
- `AsyncGzipFile`

Implementation internals live in `aiogzip._common`, `aiogzip._binary`, and `aiogzip._text`. Treat those modules as private and unstable unless symbols are explicitly re-exported by `aiogzip`.

::: aiogzip
