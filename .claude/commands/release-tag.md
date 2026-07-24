# Release Tag

Tag a merged release and publish to PyPI + GitHub Releases. Run this after a `/release-prep` PR has been merged.

## Steps

### 1. Verify merge

- Confirm the active `gh` account is `geoff-davis` (`gh api user --jq .login`);
  switch with `gh auth switch --user geoff-davis` if not. The active account
  can silently revert between sessions, and releases published from the wrong
  account fail or misattribute.
- Confirm we are on the `main` branch. If not, switch to it.
- Run `git pull` to get the latest.
- Read the current version from `src/aiogzip/__init__.py` (`__version__`).
- Verify the version has been bumped (i.e., no tag `v<version>` exists yet).
  Check `git tag -l "v<version>"` by its *output*, not its exit code — it
  exits 0 even when nothing matches.
- If a tag already exists for this version, tell the user and stop.
- Determine whether this is a pre-release: any PEP 440 pre/dev segment in the
  version (`a`, `b`, `rc`, or `.dev`, e.g. `2.0.0a1`) counts. A version that
  is only dotted digits (e.g. `1.11.0`) is a stable release. This drives the
  release flags in step 4.

### 2. Confirm with user

- Show the user the version that will be tagged and ask for confirmation before proceeding.

### 3. Tag and push

- Run `git tag v<version>` on the current HEAD.
- Run `git push origin v<version>`.
- Tell the user the tag has been pushed and that the PyPI publish workflow has been triggered.

### 4. Create GitHub Release

- Read the `[<version>]` section from `CHANGELOG.md` to use as release notes.
- Stable release:
  `gh release create v<version> --title "v<version>" --latest --notes "<changelog section>"`.
- Pre-release:
  `gh release create v<version> --title "v<version>" --prerelease --notes "<changelog section>"`.
  Never pass `--latest` for a pre-release — it would steal the "Latest" badge
  from the newest stable release, making the pre-release the default release
  page and the version served by "latest release" links.
- After creating, verify the flags with `gh release list --limit 3`: the new
  release must show `Pre-release` (or `Latest` for a stable release), and for
  a pre-release the previous stable must still show `Latest`.
- Report the release URL to the user.

### 5. Verify publish and clean up

- Watch the tag-triggered publish workflow to completion
  (`gh run watch <run-id> --exit-status`) and confirm both the `test` and
  `publish` jobs succeeded.
- Confirm the version is actually live on PyPI (e.g.
  `curl -s https://pypi.org/pypi/aiogzip/json` and check `releases`). For a
  pre-release, also confirm `info.version` (the default resolution) still
  points at the newest stable version.
- Only report the release as complete after both checks pass.
- Delete the local release branch if it still exists (`release/v<version>`).
