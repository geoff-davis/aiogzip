#!/usr/bin/env bash
# Pre-push guard: fail when origin/main has commits that are not in the
# history of the branch being pushed — i.e. the branch was cut from (or has
# drifted behind) a stale main. This repo is developed from multiple
# machines, so a locally-green branch can still be based on old code.
# See CLAUDE.md "Sync Before Working".
set -u

# Fail open when offline: a fetch failure must not block pushing.
if ! git fetch --quiet origin main 2>/dev/null; then
    echo "check-branch-fresh: could not fetch origin/main (offline?); skipping check" >&2
    exit 0
fi

behind=$(git rev-list --count HEAD..origin/main)
if [ "${behind}" -gt 0 ]; then
    echo "check-branch-fresh: origin/main has ${behind} commit(s) missing from this branch:" >&2
    git log --oneline HEAD..origin/main | head -10 >&2
    echo "" >&2
    echo "The branch is based on a stale main. Rebase before pushing:" >&2
    echo "    git rebase origin/main" >&2
    echo "Or, if being behind is intentional, skip once with:" >&2
    echo "    SKIP=check-branch-fresh git push" >&2
    exit 1
fi
exit 0
