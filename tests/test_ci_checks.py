"""the ci reward assertion must fail loudly on errors, wrong rewards and empty jobs."""

import json

from incidentforge.ci_checks import check, main


def trial(job, name, reward=None, exc=None):
    d = job / name
    d.mkdir(parents=True)
    vr = None if reward is None else {"rewards": {"reward": reward}}
    (d / "result.json").write_text(json.dumps({"trial_name": name, "verifier_result": vr, "exception_info": exc}))


def test_all_trials_matching_passes(tmp_path):
    trial(tmp_path, "a", 1.0)
    trial(tmp_path, "b", 1.0)
    assert check(tmp_path, 1.0) == []
    assert main([str(tmp_path), "1.0"]) == 0


def test_wrong_reward_errored_and_missing_reward_all_fail(tmp_path):
    trial(tmp_path, "ok", 0.0)
    trial(tmp_path, "solved", 1.0)
    trial(tmp_path, "crashed", 0.0, exc={"type": "Timeout"})
    trial(tmp_path, "noreward")
    problems = check(tmp_path, 0.0)
    assert len(problems) == 3
    assert main([str(tmp_path), "0.0"]) == 1


def test_empty_job_fails(tmp_path):
    assert check(tmp_path, 1.0)
