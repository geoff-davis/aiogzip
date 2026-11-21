# Public API contract data

`public_api_2_1.json` is the curated runtime contract for the aiogzip 2.1
release line. CI checks it on every supported Python version.
`public_api_2_0.json` is the frozen 2.0 baseline and never changes: a minor
release may add to the contract, and `tests/test_public_api_contract.py`
fails if the current manifest drops or alters anything the baseline holds. It intentionally
does not capture private implementation details, engine diagnostic strings,
the literal package version, complete dynamic error messages, or example
output wording.

After a reviewed, intentional public-contract change, regenerate it from the
repository root:

```console
uv run python scripts/capture_public_api.py \
  --output tests/data/public_api_2_1.json
uv run python scripts/capture_public_api.py \
  --check tests/data/public_api_2_1.json
uv run pytest -q tests/test_public_api_contract.py tests/test_public_api_typing.py
```

Review the JSON diff against `plans/api/v2.0.0b1-api-decisions.md` and
`docs/stability.md`. A changed
manifest is evidence to review, not an instruction to accept the change.
