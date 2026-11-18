# Finale playbook (20 Dec)

Goal: the organisers hand over a repository; within the session we show validated IncidentForge tasks
generated from it, checked by Harbor, with at least one model evaluated.

## Before the event

- [ ] Fresh clone of `main`, `uv sync`, `uv run pytest -q` green.
- [ ] Docker running with ≥ 8 GB; base images pulled: `python:3.12-slim-bookworm`, `golang:1.25-bookworm`,
      `ghcr.io/astral-sh/uv:0.9.26`.
- [ ] Harbor installed (`uv tool install harbor==0.26.0`), `harbor agent list` works.
- [ ] Claude Code logged in (`claude -p "ok"`) and/or `GEMINI_API_KEY` in `.env`.
- [ ] `uv run forge budget` shows headroom under the cap.
- [ ] Rehearse: `scripts/finale_dry_run.sh <some small repo> <sha> python` end to end.

## On the day

### 1. Pin the repo (2 min)

```bash
git ls-remote <repo_url> HEAD            # or the tag/commit the organisers name
```

Pick the language: `python` or `go`. For anything else, say so early and fall back to showing the pipeline
on our two prepared targets.

### 2. Scaffold, build, prove the suite (5–15 min)

```bash
scripts/finale_dry_run.sh <repo_url> <commit> <python|go> <name> 3
```

The script writes `src/incidentforge/targets/<name>.yaml` and `targets/env/<name>/` from the generic template,
builds `incidentforge/<name>-env:dry`, runs the repo's suite inside it, then runs `forge run --n 3` and
`forge validate`, printing per-step timings and the time to the first accepted task. Logs go to
`work/finale/<name>/<step>.log`.

### 3. If a step fails

| Step | Typical cause | Fix |
|---|---|---|
| `build` | system library or service missing | add `apt-get install` / start the service in `targets/env/<name>/Dockerfile`; re-run (the template is kept) |
| `build` (python) | unusual dependency layout | replace the install `RUN` with the repo's documented install command |
| `repo-suite` | tests need a database/cache | install and start it inside the container (see the fastapi-template env: Postgres in the same container) |
| `repo-suite` | a few tests are broken at that commit | set `test_command` in the target yaml to deselect them (`run_tests -q --deselect …` / `run_tests -skip …`) |
| `forge-run` | no surfaces found | point `source_root` at the package dir; pass `--family` for the families that fit the repo |
| `forge-run` | most tasks rejected | read `reports/validation/<task>.json`; the failing gate says why; try another family |

### 4. Show the result (5 min)

```bash
harbor run -p tasks/<name> -a oracle     # 1.0 on every task
harbor run -p tasks/<name> -a nop        # 0.0 on every task
uv run forge eval --tasks tasks/<name> --model gemini/gemini-3.8-flash
uv run forge report && open reports/index.html
```

Walk the judges through one task: `instruction.md`, a fault test, the validation log.

## Timings from rehearsals

| Repo | Language | Build | Suite | First accepted task | Total |
|---|---|---|---|---|---|
| python-dotenv (small config library), `--n 3`, claude-code backend | python | 60 s cold / 1 s cached | 3 s (287 tests) | 521 s | 1184 s; 3/3 accepted (env-aware-naming, config-round-trip, fail-fast-config), 50% of generations accepted, 16/17 mutants killed |
| viper (config library) | go | 103 s | 1 s | not run yet | scaffold, build and suite only |

Plan for roughly 10 minutes to the first accepted task and 20 minutes for three on a laptop shared with other jobs;
start the run before walking the judges through the slides.
