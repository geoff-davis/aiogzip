"""The WP10 PR seed set: generated public-API sequences against the model.

Each seed generates one scenario, replays it through the public interpreter
on the candidate, and checks every event against the model (public replay)
and the candidate's private state against the model's tables (observer).
The C0 and b1 differentials run locally and in the release run, not here;
see "Seeds, minimization and CI" in plans/design/v2.0.0b2-wp10-qualification.md.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import pytest
from generator import generate
from interpreter import replay
from model import LIFECYCLE, READ_HEALTH, make_checker
from observer import Observer

import aiogzip

# Seeds outside the base range that once exposed a defect or a model gap,
# plus 5767, the only seed below 6000 that aborts a BROKEN reader.
REGRESSION_SEEDS = (
    943, 1062, 1071, 1149, 1494, 1506, 1530, 1726,
    1737, 1754, 1787, 1818, 2105, 2254, 5767,
)  # fmt: skip
PR_SEEDS = tuple(range(1000)) + REGRESSION_SEEDS

# Table rows the generator cannot reach, each with the focused test that
# covers it instead (path, test function).
TESTS = Path(__file__).resolve().parent.parent
COVERED_ELSEWHERE = {
    ("lifecycle", "OPENING->cleanup_raises_exception"): (
        "test_open_settlement.py",
        "test_failed_header_preserves_primary_error_when_cleanup_fails",
    ),
    ("lifecycle", "OPENING->cleanup_raises_base_exception"): (
        "test_open_qualification.py",
        "test_native_cleanup_stays_reserved_through_repeated_cancel",
    ),
    ("lifecycle", "OPENING->exceptional_context_exit"): (
        "test_open_qualification.py",
        "test_context_exit_during_open_does_not_abandon_opener",
    ),
}


@cache
def _run(seed: int) -> tuple[list[str], frozenset[tuple[str, str]]]:
    scenario = generate(seed)
    checker = make_checker(scenario, aiogzip.engine_info().decompression)
    observer = Observer(checker)

    def hook(handle, event, context):
        checker.observe(event)
        observer(handle, event, context)

    replay(aiogzip, scenario, (hook,))
    return checker.violations + observer.violations, frozenset(checker.coverage)


@pytest.mark.parametrize("seed", PR_SEEDS)
def test_seed_matches_the_model(seed):
    violations, _coverage = _run(seed)
    assert not violations, f"seed {seed}:\n" + "\n".join(violations)


def test_seed_set_covers_every_table_row():
    covered = frozenset().union(*(_run(seed)[1] for seed in PR_SEEDS))
    rows = {("lifecycle", f"{row.source.value}->{row.event}") for row in LIFECYCLE}
    rows |= {("health", f"{health.value}->{event}") for health, event in READ_HEALTH}
    assert covered <= rows, sorted(covered - rows)
    assert rows - covered == set(COVERED_ELSEWHERE)
    for path, name in COVERED_ELSEWHERE.values():
        source = (TESTS / path).read_text(encoding="utf-8")
        assert re.search(rf"^(async )?def {name}\(", source, re.M), (path, name)
