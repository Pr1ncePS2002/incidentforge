"""harbor wrapper: command building, env passing and job json parsing."""

import json
import subprocess
from pathlib import Path

import pytest

from incidentforge import harbor


def _trial(job: Path, name: str, rewards: dict | None, exc: dict | None = None, usage: dict | None = None) -> None:
    d = job / name
    d.mkdir(parents=True)
    data = {
        "task_name": name.split("__")[0],
        "trial_name": name,
        "verifier_result": {"rewards": rewards} if rewards is not None else None,
        "exception_info": exc,
        "agent_result": usage or {"n_input_tokens": None, "n_output_tokens": None, "cost_usd": None},
    }
    (d / "result.json").write_text(json.dumps(data))


def test_read_trials_and_rewards(tmp_path):
    job = tmp_path / "job"
    _trial(job, "a__1", {"reward": 1, "feature_tests": 1, "repo_suite": 1})
    _trial(
        job,
        "b__2",
        {"reward": 0, "feature_tests": 0, "repo_suite": 1},
        usage={"n_input_tokens": 120, "n_cache_tokens": 5, "n_output_tokens": 30, "cost_usd": 0.01},
    )
    _trial(job, "c__3", None, exc={"exception_type": "AgentTimeoutError", "exception_message": "slow"})
    (job / "result.json").write_text("{}")  # job-level json is not a trial
    trials = harbor.read_trials(job)
    assert [t.trial_name for t in trials] == ["a__1", "b__2", "c__3"]
    assert trials[0].rewards == {"reward": 1.0, "feature_tests": 1.0, "repo_suite": 1.0}
    assert (trials[1].input_tokens, trials[1].cache_tokens, trials[1].output_tokens) == (120, 5, 30)
    assert trials[1].cost_usd == 0.01 and trials[1].task_name == "b"
    assert trials[2].reward is None and "AgentTimeoutError" in (trials[2].error or "")
    assert harbor.read_rewards(job) == {"a__1": 1.0, "b__2": 0.0, "c__3": 0.0}


def test_build_command():
    cmd = harbor.build_command(Path("t"), "oracle", "j", Path("jobs"), model="m/x", extra_args=["-k", "3"])
    assert cmd[:2] == ["harbor", "run"]
    assert cmd[cmd.index("-p") + 1] == "t" and cmd[cmd.index("-a") + 1] == "oracle"
    assert cmd[cmd.index("--job-name") + 1] == "j" and cmd[cmd.index("-m") + 1] == "m/x"
    assert cmd[-2:] == ["-k", "3"]
    assert "-m" not in harbor.build_command(Path("t"), "nop", "j", Path("jobs"))


def test_run_job_passes_env_and_returns_dir(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        (tmp_path / "j").mkdir()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("KEEP_ME", "1")
    out = harbor.run_job(Path("t"), "oracle", "j", tmp_path, env={"GEMINI_API_KEY": "k"})
    assert out == tmp_path / "j"
    assert seen["env"]["GEMINI_API_KEY"] == "k" and seen["env"]["KEEP_ME"] == "1"


def test_run_job_raises_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "boom"))
    with pytest.raises(harbor.HarborError, match="boom"):
        harbor.run_job(Path("t"), "oracle", "j", tmp_path)
