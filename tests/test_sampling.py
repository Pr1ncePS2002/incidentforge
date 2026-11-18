"""frequency-weighted family sampling."""

from collections import Counter

import pytest

from incidentforge.families import CORE, EXTENDED
from incidentforge.families.sampling import load_weights, normalise, pick_families


def test_taxonomy_covers_all_eight_families_and_sums_to_one() -> None:
    weights = load_weights()
    assert set(weights) == set(CORE) | set(EXTENDED)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_pick_is_deterministic_per_seed() -> None:
    assert pick_families(20, seed=7) == pick_families(20, seed=7)
    assert pick_families(20, seed=7) != pick_families(20, seed=8)


def test_counts_follow_weights() -> None:
    counts = Counter(pick_families(50))
    assert sum(counts.values()) == 50
    assert counts["config-round-trip"] == 10
    assert counts["fail-fast-config"] == 8
    assert counts["hot-reload-config"] == 4


def test_renormalises_over_available_families() -> None:
    picks = pick_families(10, available=["fail-fast-config", "config-round-trip", "unknown"])
    assert set(picks) == {"fail-fast-config", "config-round-trip"}
    assert Counter(picks) == {"config-round-trip": 6, "fail-fast-config": 4}


def test_custom_weights_and_small_n() -> None:
    assert pick_families(1, weights={"a": 0.2, "b": 0.8}) == ["b"]
    assert pick_families(0) == []


def test_errors() -> None:
    with pytest.raises(ValueError):
        pick_families(-1)
    with pytest.raises(ValueError):
        normalise({"a": 1.0}, available=["b"])
    with pytest.raises(ValueError):
        normalise({"a": 0.0})
