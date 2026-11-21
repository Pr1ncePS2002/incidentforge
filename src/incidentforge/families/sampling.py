"""frequency-weighted family sampling; weights are the relative frequency of each outage class."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from incidentforge.models import Surface

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"


def load_weights(path: Path = TAXONOMY_PATH) -> dict[str, float]:
    raw = json.loads(path.read_text())
    return {str(k): float(v) for k, v in raw.items()}


def normalise(weights: Mapping[str, float], available: Iterable[str] | None = None) -> dict[str, float]:
    """keep only usable families and rescale to sum 1; a target without surfaces for a family drops it."""
    allowed = set(weights) if available is None else set(available) & set(weights)
    kept = {k: weights[k] for k in sorted(allowed) if weights[k] > 0}
    total = sum(kept.values())
    if not kept or total <= 0:
        raise ValueError("no family with positive weight is available")
    return {k: v / total for k, v in kept.items()}


def pick_families(
    n: int,
    weights: Mapping[str, float] | None = None,
    available: Iterable[str] | None = None,
    seed: int = 0,
) -> list[str]:
    """return n family slugs; largest-remainder quotas so small n still tracks the weights, order shuffled by seed."""
    if n < 0:
        raise ValueError("n must be >= 0")
    probs = normalise(load_weights() if weights is None else weights, available)
    quotas = {k: math.floor(p * n) for k, p in probs.items()}
    # hand leftover slots to the largest remainders, ties broken by weight then name for determinism
    leftover = n - sum(quotas.values())
    order = sorted(probs, key=lambda k: (-(probs[k] * n - quotas[k]), -probs[k], k))
    for k in order[:leftover]:
        quotas[k] += 1
    picks = [k for k in sorted(quotas) for _ in range(quotas[k])]
    random.Random(seed).shuffle(picks)
    return picks


def rank_surfaces(surfaces: Sequence[Surface], seed: int = 0) -> list[Surface]:
    """seeded weighted order by risk_score (D-65): uncovered surfaces tend to come first, none are dropped."""
    rng = random.Random(seed)
    keyed: list[tuple[float, int, Surface]] = []
    for i, s in enumerate(surfaces):
        weight = s.risk_score if s.risk_score and s.risk_score > 0 else 1.0
        # efraimidis-spirakis key u^(1/w): one draw per item gives a weighted permutation
        keyed.append((rng.random() ** (1.0 / weight), -i, s))
    return [s for _, _, s in sorted(keyed, key=lambda k: (k[0], k[1]), reverse=True)]
