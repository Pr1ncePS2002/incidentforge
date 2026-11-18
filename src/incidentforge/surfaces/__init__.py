"""find code surfaces in a checked-out repo. owner: phase 2 (python), phase 3 (go)."""

from pathlib import Path

from incidentforge.models import Language, Surface


def find_surfaces(repo_dir: Path, language: Language, kinds: set[str] | None = None) -> list[Surface]:
    if language is Language.go:
        from incidentforge.surfaces.go import find_go_surfaces

        return find_go_surfaces(repo_dir, kinds)
    if language is Language.python:
        from incidentforge.surfaces.python import find_python_surfaces

        return find_python_surfaces(repo_dir, kinds)
    raise NotImplementedError
