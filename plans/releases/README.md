# Release artifact records

Each `v<version>.sha256` file records, in `sha256sum` format, the exact wheel
and sdist a release publishes. Release preparation writes it from a build of
the release commit (see `.claude/commands/release-prep.md`). The publish
workflow builds the tagged commit with the pinned tools, smoke-tests the
installed artifacts, and uploads them only if
`scripts/verify_release_artifacts.py` finds exactly the recorded files with
the recorded hashes; it checks again right before the upload.

`plans/` is not part of the sdist, so committing a record never changes the
hashes it records. `tests/test_verify_release_artifacts.py` guards that.
