"""task difficulty and fix scope as two separate labels (D-91, provisional thresholds D-98)."""

from __future__ import annotations

# blast radius did not track pass rate (F-51), so it only describes how far a fix reaches
EASY_MAX_FAULTS = 3
HARD_MIN_FAULTS = 6


def difficulty_from_faults(faults: int) -> str:
    if faults >= HARD_MIN_FAULTS:
        return "hard"
    if faults <= EASY_MAX_FAULTS:
        return "easy"
    return "medium"


def fix_scope(files: int) -> str:
    if files >= 4:
        return "4+ files"
    if files >= 2:
        return "2-3 files"
    return "1 file"
