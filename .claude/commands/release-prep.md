# Release Prep

Prepare a new release of aiogzip. This skill handles changelog generation, version bumping, and creating the release PR.

## Arguments

- `$ARGUMENTS` — optional version string (e.g., `1.4.0`). If omitted, infer from changelog categories.

## Steps

### 1. Generate changelog entries

- Run `git describe --tags --abbrev=0` to find the latest tag.
- Run `git log <latest-tag>..HEAD --oneline` to get commits since that tag.
- Read `CHANGELOG.md` and check the `[Unreleased]` section.
- If `[Unreleased]` is empty, auto-generate entries from the commit log, grouped by category:
  - **Added** — new features or capabilities
  - **Changed** — changes to existing functionality
  - **Fixed** — bug fixes
  - **Performance** — performance improvements
  - **Documentation** — docs changes
  - **Refactor** — code restructuring without behavior change
- Present the generated entries to the user and ask for confirmation before proceeding.

### 2. Determine version

- Read the current version from `src/aiogzip/__init__.py` (`__version__`).
- If a version was provided as `$ARGUMENTS`, use that.
- Otherwise, infer the bump type from the changelog categories using semver conventions:
  - If there are **Added** or **Changed** entries → suggest a **minor** bump
  - If there are only **Fixed**, **Documentation**, **Performance**, or **Refactor** entries → suggest a **patch** bump
- Present the suggested version to the user and ask for confirmation.

### 3. Update CHANGELOG.md

- Replace the empty `[Unreleased]` section content with a fresh blank section.
- Insert a new section `[<version>] - <YYYY-MM-DD>` below `[Unreleased]` with the generated/confirmed entries.

### 4. Bump version

- Update `__version__` in `src/aiogzip/__init__.py` to the new version.

### 5. Create release branch and PR

- Create branch `release/v<version>` from current HEAD.
- Stage `CHANGELOG.md` and `src/aiogzip/__init__.py`.
- Commit with message: `Prepare release v<version>`
- Push the branch.
- Create a PR with title `Prepare release v<version>` and body summarizing the changelog entries.
- Report the PR URL to the user.
- Remind the user: after CI passes and the PR is merged, run `/release-tag` to tag and publish.
