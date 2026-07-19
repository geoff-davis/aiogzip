# Migrating from `gzip.open`

`aiogzip.open()` accepts the same paths, modes, and keyword arguments as the
stdlib's `gzip.open()`, and it reads and writes the same `.gz` format. Exactly
three things change:

| | `gzip` | `aiogzip` |
|---|---|---|
| Opening | `with gzip.open(...) as f:` | `async with aiogzip.open(...) as f:` |
| Line iteration | `for line in f:` | `async for line in f:` |
| Reads and writes | `f.read()`, `f.write(data)` | `await f.read()`, `await f.write(data)` |

## Before / after

```python
# stdlib gzip
import gzip

def count_lines(path):
    with gzip.open(path, "rt") as f:
        return sum(1 for _ in f)
```

```python
# aiogzip
import aiogzip

async def count_lines(path):
    async with aiogzip.open(path, "rt") as f:
        return sum([1 async for _ in f])
```

Everything else carries over unchanged: mode strings (`"rb"`, `"rt"`, `"wb"`,
`"wt"`, append, exclusive), `compresslevel`, text-mode `encoding` / `errors` /
`newline`, and interoperability — files written by either library are read by
the other.

If you forget and use `with` or `for`, aiogzip raises a `TypeError` that says
exactly what to change (e.g. `"must be used with 'async with', not 'with'"`).

Next steps: [Examples](examples.md) for common tasks,
[Recipes](recipes.md) for streaming patterns, and the
[Performance Guide](performance.md) for tuning.
