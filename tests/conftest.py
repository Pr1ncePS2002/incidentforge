"""shared fixtures."""

import pytest

REGRESSION_IDS = ["tests/test_existing.py::test_kept"]


@pytest.fixture(autouse=True)
def _no_docker_collection(request, monkeypatch):
    # write_task collects pass_to_pass in the target image; unit tests get a fixed list instead
    if request.node.get_closest_marker("docker") is None:
        monkeypatch.setattr("incidentforge.package.pass_to_pass", lambda target: list(REGRESSION_IDS))
