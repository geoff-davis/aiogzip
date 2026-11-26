import collections
import glob
import json
import re
import sys

B = sys.argv[1]
ROWS = [
    (
        "Bulk text write, level 6",
        "Text write (bulk, compression level 6)",
        "aiogzip_time",
        "gzip_time",
    ),
    (
        "Bulk LF-only text read",
        "Text read (bulk, identical fixture)",
        "aiogzip_time",
        "gzip_time",
    ),
    (
        "Default line iteration",
        "Text line iteration (default, identical fixture)",
        "aiogzip_time",
        "gzip_time",
    ),
    (
        "Tuned JSONL line iteration",
        "Text line iteration (tuned, identical fixture)",
        "aiogzip_time",
        "gzip_time",
    ),
    (
        "Tuned JSONL read and parse",
        "JSONL read and parse (identical fixture)",
        "aiogzip_time",
        "gzip_time",
    ),
    (
        "JSONL batched readlines",
        "JSONL batched readlines and parse (identical fixture)",
        "aiogzip_time",
        "gzip_time",
    ),
    (
        "Compressible read(-1)",
        "Read-all isolated (compressible, read-only timing)",
        "aiogzip_read_best",
        "gzip_read_best",
    ),
    (
        "Ten files, 10 ms latency",
        "Concurrent I/O (10 files, 10ms delay each)",
        "async_time",
        "sync_time",
    ),
]


def sec(s):
    m = re.match(r"([\d.]+)(ms|s)$", s)
    return float(m[1]) * (1e-3 if m[2] == "ms" else 1)


data = collections.defaultdict(list)  # (tag, engine, name) -> [(a, g)]
envs = set()
for f in sorted(glob.glob(B + "/table-*.json")):
    d = json.load(open(f))
    tag, engine = re.match(r".*table-(v[\d.a]+)-(stdlib|zlib-ng)-r\d", f).groups()
    envs.add(
        (
            tag,
            d["environment"]["target_commit"][:7],
            d["environment"]["target_dirty"],
            d["environment"]["python_version"].split()[0],
            d["status"],
        )
    )
    for r in d["results"]:
        for label, name, ak, gk in ROWS:
            if r["name"] == name and ak in r["metrics"]:
                data[(tag, engine, label)].append(
                    (sec(r["metrics"][ak]), sec(r["metrics"][gk]))
                )
for e in sorted(envs):
    print(e)
for engine in ("stdlib", "zlib-ng"):
    print(
        f"\n== {engine}: aiogzip/gzip time ratio per round (>1 = aiogzip slower); min-of-rounds ratio; aiogzip min ms"
    )
    for label, *_ in ROWS:
        for tag in ("v1.11.0", "v2.0.0a1", "v2.0.2"):
            v = data.get((tag, engine, label))
            if not v:
                print(f"{label:28s} {tag:9s} MISSING")
                continue
            rounds = " ".join(f"{a / g:5.2f}" for a, g in v)
            amin = min(a for a, _ in v)
            gmin = min(g for _, g in v)
            print(
                f"{label:28s} {tag:9s} rounds [{rounds}]  min-ratio {amin / gmin:5.2f}  aiogzip {amin * 1e3:7.2f} ms  gzip {gmin * 1e3:7.2f} ms"
            )
