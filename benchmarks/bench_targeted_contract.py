"""Shared producer/reader contract for targeted benchmark captures."""

from __future__ import annotations

from typing import Any

TARGETED_BENCHMARK = "aiogzip-2.0.0b1-targeted-timing-investigation"
RAW_CHANGE_FORMULA = "(raw candidate / raw baseline - 1) * 100"
CANONICAL_SIDES = {"baseline", "candidate"}


def _is_archived_b1_version(version: object) -> bool:
    return isinstance(version, str) and (
        version == "2.0.0b1" or version.startswith("2.0.0b1.")
    )


def _legacy_b1_candidate_side(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> str | None:
    """Infer orientation only for the archived a4/b1 investigation pair."""
    versions = {
        "baseline": baseline.get("version"),
        "candidate": candidate.get("version"),
    }
    a4_sides = [side for side, version in versions.items() if version == "2.0.0a4"]
    b1_sides = [
        side for side, version in versions.items() if _is_archived_b1_version(version)
    ]
    if len(a4_sides) == 1 and len(b1_sides) == 1 and a4_sides != b1_sides:
        return b1_sides[0]
    return None


def _require_candidate_side(value: object, label: str) -> str:
    if not isinstance(value, str) or value not in CANONICAL_SIDES:
        raise ValueError(f"{label} has invalid canonical_candidate_side")
    return value


def _require_candidate_commit(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} has invalid canonical_candidate_commit")
    return value


def require_explicit_orientation(
    configuration: dict[str, Any], *, label: str
) -> tuple[str, str]:
    """Validate the orientation fields required from a new producer."""
    candidate_side = _require_candidate_side(
        configuration.get("canonical_candidate_side"), label
    )
    canonical_commit = _require_candidate_commit(
        configuration.get("canonical_candidate_commit"), label
    )
    return candidate_side, canonical_commit


def validate_candidate_commit_binding(
    candidate_side: str,
    canonical_commit: str,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    label: str,
) -> None:
    """Bind an explicit orientation to the selected side's exact commit."""
    selected = baseline if candidate_side == "baseline" else candidate
    selected_commit = selected.get("commit")
    if canonical_commit != selected_commit:
        raise ValueError(
            f"{label} canonical_candidate_commit={canonical_commit!r} contradicts "
            f"the {candidate_side} source commit {selected_commit!r}"
        )


def validate_canonical_orientation(
    configuration: dict[str, Any],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    label: str,
    allow_legacy: bool,
) -> tuple[str, list[str]]:
    """Validate explicit orientation, with a4/b1 inference for archival records."""
    warnings: list[str] = []
    legacy_side = _legacy_b1_candidate_side(baseline, candidate)
    candidate_side = configuration.get("canonical_candidate_side")
    if candidate_side is None:
        if not allow_legacy:
            raise ValueError(
                f"{label} lacks canonical_candidate_side; use --allow-legacy "
                "only for an archived a4/b1 record"
            )
        if legacy_side is None:
            raise ValueError(
                f"{label} lacks canonical_candidate_side and its orientation "
                "cannot be inferred"
            )
        candidate_side = legacy_side
        warnings.append(
            f"{label}: canonical candidate side inferred from source versions"
        )
    else:
        candidate_side = _require_candidate_side(candidate_side, label)

    canonical_commit = configuration.get("canonical_candidate_commit")
    if canonical_commit is None:
        if not allow_legacy:
            raise ValueError(
                f"{label} lacks canonical_candidate_commit; use --allow-legacy "
                "only for an archived a4/b1 record"
            )
        if legacy_side is None:
            raise ValueError(
                f"{label} lacks canonical_candidate_commit and its orientation "
                "cannot be attested"
            )
        warnings.append(
            f"{label}: canonical candidate commit was not producer-recorded"
        )
    else:
        canonical_commit = _require_candidate_commit(canonical_commit, label)
        validate_candidate_commit_binding(
            candidate_side,
            canonical_commit,
            baseline,
            candidate,
            label=label,
        )

    if legacy_side is not None and candidate_side != legacy_side:
        raise ValueError(
            f"{label} canonical_candidate_side={candidate_side!r} contradicts "
            f"the archived a4/b1 source versions; expected {legacy_side!r}"
        )
    if baseline.get("commit") == candidate.get("commit"):
        warnings.append(
            f"{label}: both sides attest the same source commit; canonical "
            "candidate side labels measurement orientation only"
        )
    return candidate_side, warnings
