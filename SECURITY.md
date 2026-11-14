# Security Policy

## Supported Versions

Security fixes are released on top of the latest release of each supported
line. The 1.x line, which still serves Python 3.8 through 3.10, receives
security fixes only, until 2027-04-30; after that date it is unsupported.

| Version line | Supported |
| --- | --- |
| Latest 2.x release | :white_check_mark: |
| Latest 1.x maintenance release | :white_check_mark: Security fixes only, until 2027-04-30 |
| Older 2.x releases and 2.0 prereleases | :x: Upgrade to the latest 2.x release |
| Older 1.x releases | :x: |

## Reporting a Vulnerability

We take the security of aiogzip seriously. If you believe you have found a security vulnerability, please report it to us responsibly.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to:

- **Email**: geoff@keksi.ai
- **Subject**: [SECURITY] aiogzip vulnerability report

### What to Include

Please include the following information in your report:

- Description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Any suggested fixes (if available)

### Response Timeline

- **Initial Response**: Within 48 hours of receiving your report
- **Status Update**: Within 7 days with an assessment of the report
- **Fix Timeline**: We aim to release security fixes within 30 days for critical issues

### Disclosure Policy

- We request that you give us reasonable time to address the issue before public disclosure
- We will credit you in the security advisory unless you prefer to remain anonymous
- Once a fix is released, we will publish a security advisory on GitHub

## Handling Untrusted Gzip Input

A gzip stream from a source you do not control can be a decompression bomb,
can hold any number of members, and can carry any header metadata. aiogzip
has the controls described below, but **the decompressed-size limit is off
by default**. Two other limits apply without any setting: the rewind cache
is capped at 128 MiB by default (`max_rewind_cache_size=None` removes the
cap), and a member header is limited to a fixed 128 MiB. This section
applies to aiogzip 2.x.

The maintained recipe is
[Processing untrusted gzip input](https://geoff-davis.github.io/aiogzip/latest/recipes/#processing-untrusted-gzip-input).
This section lists what each entry point does and does not limit.

### Entry points and their defaults

Every entry point that decompresses takes `max_decompressed_size`, and it
defaults to `None` (no limit) in all of them.

| Entry point | `max_decompressed_size` | Other limits |
| --- | --- | --- |
| `aiogzip.open()` in a read mode, binary or text (also `AsyncGzipFile`, `AsyncGzipBinaryFile`, `AsyncGzipTextFile`) | `None` | `max_rewind_cache_size`, default 128 MiB |
| `aiogzip.read()` | `None` | `max_rewind_cache_size`, default 128 MiB |
| `aiogzip.decompress_chunks()` | `None` | None |
| `aiogzip.GzipDecoder` | `None` | `collect_member_info`, default `False` |
| `aiogzip.inspect()` | `None` | None; always keeps a record for each member |
| `aiogzip.verify()` | `None` | None |
| `python -m aiogzip inspect` and `verify` | No option; always unlimited | None |

Two things are not limited anywhere:

- **The number of gzip members.** There is no member-count parameter.
- **The compressed input size.** aiogzip reads until the source ends. Check
  the file size, or cap the bytes you accept from the network, before you
  hand the data to aiogzip.

### Limit the decompressed size

Pass `max_decompressed_size` whenever the input is untrusted:

```python
import aiogzip

MAX_DECOMPRESSED_SIZE = 100 * 1024 * 1024  # 100 MiB


async def process_upload(path):
    async with aiogzip.open(
        path, "rb", max_decompressed_size=MAX_DECOMPRESSED_SIZE
    ) as f:
        while chunk := await f.read(64 * 1024):
            ...  # raises OSError once the limit is crossed
```

The same keyword works on the other entry points:

```python
data = await aiogzip.read(path, max_decompressed_size=MAX_DECOMPRESSED_SIZE)
result = await aiogzip.verify(path, max_decompressed_size=MAX_DECOMPRESSED_SIZE)
info = await aiogzip.inspect(path, max_decompressed_size=MAX_DECOMPRESSED_SIZE)
chunks = aiogzip.decompress_chunks(
    source, max_decompressed_size=MAX_DECOMPRESSED_SIZE
)
decoder = aiogzip.GzipDecoder(max_decompressed_size=MAX_DECOMPRESSED_SIZE)
```

How the limit behaves:

- It is a positive integer that counts decompressed bytes over the whole
  stream, across all members. On a text handle it counts bytes before
  decoding, not characters.
- Each inflate call is limited to the remaining allowance plus one byte, so
  a bomb is stopped during decompression and is not expanded first.
- Crossing it raises a plain `OSError` whose message starts with
  `decompressed output exceeded max_decompressed_size`. It is not a
  `gzip.BadGzipFile`, because the data may be valid gzip. See
  [Telling the decompression cap apart from corruption](https://geoff-davis.github.io/aiogzip/latest/errors/#telling-the-decompression-cap-apart-from-corruption).
- On a file handle it applies to every read method (`read()`, `readline()`,
  iteration, `peek()`). The count starts again when the handle rewinds, so
  it limits the size of the stream, not the total work of repeated passes.

Without the limit:

- A file handle can hold far more decompressed data than a read asks for. It
  inflates all the compressed input it has already read from the source, so
  one `read(1)` on a stream of zeros held about 257 MiB with the default
  `chunk_size` of 256 KiB. The size passed to `read()` is how much is
  returned, not how much memory is used.
- `read()` with no size, and `aiogzip.read()`, return the whole decompressed
  stream as one object. `readline()` and line iteration hold a whole line,
  and a stream with no line ending is one line.
- `decompress_chunks()` and `GzipDecoder` inflate on demand and yield chunks
  no larger than `output_chunk_size` (default 256 KiB), so the decompressed
  data they hold at one time is small. That bounds the output buffer only.
  They hold each compressed input item you pass in whole, whatever its size,
  so pass input in bounded pieces. The total output is still unlimited, and
  so is whatever your code accumulates from it.
- `verify()` and `inspect()` discard the payload, so a bomb costs processor
  time rather than memory.

With several untrusted inputs open at once, also limit the number of handles
that are open at the same time.

### Rewind cache on non-seekable sources

When `fileobj` is not seekable, a file handle keeps a copy of the
*compressed* bytes it has read, so that a backward `seek()` can replay them.
`max_rewind_cache_size` limits that copy. The default is 128 MiB for each
handle, and `None` removes the limit. When the limit is passed, the copy is
dropped and backward seeks raise `OSError`; forward reads continue.

For untrusted streams that you only read forward, lower it:

```python
async with aiogzip.open(
    None,
    "rb",
    fileobj=network_stream,
    max_decompressed_size=MAX_DECOMPRESSED_SIZE,
    max_rewind_cache_size=1024 * 1024,
) as f:
    ...
```

Files opened by path and seekable file objects are not cached.
`decompress_chunks()`, `GzipDecoder`, `inspect()` and `verify()` have no
rewind cache.

### Member count and member metadata

`max_decompressed_size` does not limit the number of members: an empty member
is 20 bytes of input and adds nothing to the count.

- `inspect()` and `GzipDecoder(collect_member_info=True)` keep a
  `GzipMemberInfo` record for every member, so their memory grows with a
  count that the sender controls. Limit the compressed input size, or use
  `verify()`, which keeps only totals.
- `GzipDecoder` with the default `collect_member_info=False`,
  `decompress_chunks()`, `verify()` and file handles keep no member records.
- A member header may be up to 128 MiB long. A longer one raises
  `gzip.BadGzipFile`. This limit is fixed and cannot be changed. When records
  are collected, each record keeps the header's file name and comment, which
  can be that large, and its extra field, which is at most 65,535 bytes. When
  records are not collected, these fields are skipped and not stored.

Header metadata comes from the sender. Treat `original_filename`, `comment`,
`extra` and `mtime` in a `GzipMemberInfo` as untrusted data. In particular,
never use `original_filename` as a path to write to: it can be absolute or
contain `..`. `python -m aiogzip inspect` prints the name with `repr()`, so
control characters in it do not reach the terminal.

### Integrity is checked at the end

Decompressed bytes can be returned before the member's CRC-32 and size have
been checked. Data from an untrusted source is verified only when:

- a file read reaches the end of the stream without an error;
- the `decompress_chunks()` iterator is exhausted without an error;
- the operation returned by `GzipDecoder.finish()` is exhausted without an
  error; or
- `verify()` or `inspect()` returns.

If output must not be acted on before it is verified, call `verify()` first,
or stage the output until the stream ends. See
[Where errors surface](https://geoff-davis.github.io/aiogzip/latest/errors/#where-errors-surface).

A valid CRC-32 shows that the stream is well formed. It does not show who
produced it: a sender can compute a correct CRC for any content. Use a
signature or a keyed digest when you need to know where the data came from.

### Command line

`python -m aiogzip inspect FILE` and `python -m aiogzip verify FILE` have no
size-limit option and always run without one. For an untrusted file, call
`aiogzip.verify()` or `aiogzip.inspect()` from Python with
`max_decompressed_size`, or run the command under an operating-system
resource limit.

### Timeouts

aiogzip sets no timeouts. A slow or stalled source keeps a read waiting, so
wrap reads from untrusted network sources in `asyncio.timeout()`. The
timeout cancels the waiting task; it is not always a hard deadline. A read
from a file opened by path, or any other read that runs in a worker thread,
runs until it settles once started, and the handle waits for it. A custom
async `fileobj` is cancelled cooperatively and can stop at once. See
[Cancellation](https://geoff-davis.github.io/aiogzip/latest/recipes/#cancellation).

### Writing

`strict_size=True` on the write side refuses to produce a member whose
`ISIZE` field would wrap at 4 GiB. It defaults to `False`.

## Contact

For general security questions or concerns, please contact:

- Email: geoff@keksi.ai
- GitHub: https://github.com/geoff-davis/aiogzip/issues

Thank you for helping keep aiogzip and its users safe!
