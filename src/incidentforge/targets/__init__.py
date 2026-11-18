"""target registry: targets/<name>.yaml describes a pinned repo. owner: phase 1 (python), phase 3 (go)."""

from pathlib import Path

import yaml

from incidentforge.models import Target

TARGETS_DIR = Path(__file__).parent


def load_target(name: str) -> Target:
    data = yaml.safe_load((TARGETS_DIR / f"{name}.yaml").read_text())
    data["env_template"] = (TARGETS_DIR / data["env_template"]).resolve()
    return Target(**data)
