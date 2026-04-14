# Release Tag

Tag a merged release and publish to PyPI + GitHub Releases. Run this after a `/release-prep` PR has been merged.

## Steps

### 1. Verify merge

- Confirm we are on the `main` branch. If not, switch to it.
- Run `git pull` to get the latest.
- Read the current version from `src/aiogzip/__init__.py` (`__version__`).
- Verify the version has been bumped (i.e., no tag `v<version>` exists yet).
- If a tag already exists for this version, tell the user and stop.

### 2. Confirm with user

- Show the user the version that will be tagged and ask for confirmation before proceeding.

### 3. Tag and push

- Run `git tag v<version>` on the current HEAD.
- Run `git push origin v<version>`.
- Tell the user the tag has been pushed and that the PyPI publish workflow has been triggered.

### 4. Create GitHub Release

- Read the `[<version>]` section from `CHANGELOG.md` to use as release notes.
- Run `gh release create v<version> --title "v<version>" --latest --notes "<changelog section>"`.
- Report the release URL to the user.

### 5. Clean up

- Delete the local release branch if it still exists (`release/v<version>`).
- Remind the user to verify the PyPI publish succeeded at the GitHub Actions tab.
