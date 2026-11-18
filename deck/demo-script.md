# Demo video script (3–5 min)

Record in one terminal (large font, dark theme) plus a browser for the report. Run steps 2–3 once before
recording so images are cached; generation itself can be sped up in editing (say so on screen).

| # | Time | Show on screen | Say |
|---|---|---|---|
| 1 | 0:00–0:30 | README top, families table | "AI coding benchmarks test the happy path. Real outages come from a few recurring failure classes. IncidentForge turns any repo into tasks built from those classes, each with fault-injection tests." |
| 2 | 0:30–1:30 | `uv run forge run --target fastapi-template --family fail-fast-config --n 2` | "One command: find code surfaces, generate a task with Claude Code, then six gates decide whether we keep it." Point at gate lines as they print. |
| 3 | 1:30–2:15 | `ls tasks/fastapi-template/<task>/` then `cat .../instruction.md` and one fault test | "This is a Harbor task: the instruction the agent sees, the reference patch, and tests that inject the failure — here, the required setting is blank." |
| 4 | 2:15–2:45 | `cat reports/validation/<task>.json` | "Every gate is logged: fails on the base commit, passes with the reference, repo suite green, N of M mutants killed, no leak, three stable reruns." |
| 5 | 2:45–3:20 | `harbor run -p tasks -a oracle` then `-a nop` | "Harbor confirms it: reference solution scores 1.0, doing nothing scores 0.0. CI re-checks this nightly." |
| 6 | 3:20–4:10 | `uv run forge report`, open `reports/index.html` | "We evaluated <models> on <N> tasks. <headline finding, from reports/summary.json>." |
| 7 | 4:10–4:30 | `uv run forge budget` | "Paid API use is capped before every call; total spend $<x> of $70." |
| 8 | 4:30–4:50 | Go target: `ls tasks/<go-target>/` | "Same pipeline on a Go repo — the factory is repo-agnostic." |
| 9 | 4:50–5:00 | repo URL | "Code, dataset and docs are MIT on GitHub." |

Fill `<…>` from `reports/summary.json` before recording. Never show `.env`, API keys, or any employer name.
