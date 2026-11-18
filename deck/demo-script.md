# Demo video script (3–5 min)

Record in one terminal (large font, dark theme) plus a browser for the report. Run steps 2 and 5 once before
recording so images are cached; generation itself can be sped up in editing (say so on screen).

| # | Time | Show on screen | Say |
|---|---|---|---|
| 1 | 0:00–0:30 | README top, families table | "AI coding benchmarks test the happy path. Real outages come from a few recurring failure classes. IncidentForge turns any repo into tasks built from those classes, each with fault-injection tests." |
| 2 | 0:30–1:30 | `uv run forge run --target fastapi-template --family fail-fast-config --n 2` | "One command: find code surfaces, generate a task with Claude Code, then six gates decide whether we keep it." Point at gate lines as they print. |
| 3 | 1:30–2:15 | `ls tasks/fastapi-template/ff-001-email-config/`, then `cat` its `instruction.md` and `tests/feature/tests/test_forge_email_config.py` | "This is a Harbor task: the instruction the agent sees, the reference patch, and tests that inject the failure. Here, a mail host is set without a sender address." |
| 4 | 2:15–2:45 | `cat reports/validation/fastapi-template/ff-001-email-config.json` | "Every gate is logged: fails on the base commit, passes with the reference, repo suite green, 6 of 6 mutants killed, no leak, three stable reruns." |
| 5 | 2:45–3:20 | `harbor run -p tasks/fastapi-template/ff-001-email-config -a oracle`, then `-a nop` | "Harbor confirms it: the reference solution scores 1.0, doing nothing scores 0.0. CI re-checks every task this way nightly." |
| 6 | 3:20–4:10 | open `reports/index.html` (built by `uv run forge report`) | "34 tasks, 8 families, a Python and a Go repo; every task passed all gates and the tests killed 89% of 201 mutants. Harbor's Claude Code agent passes 98%. Gemini 2.5 Flash and 3.8 Flash through the terminus-2 agent pass 33% and 28%; the agents differ, so compare within one agent. When the Gemini runs fail, they fail on an injected fault 49 times versus 21 on the happy path: models build the feature but miss the failure modes. Hardest family: config round-trip; easiest: environment-aware naming. With 60 turns instead of 30, 3.8 Flash goes from 30% to 80% on a 10-task subset, so the turn budget matters too." |
| 7 | 4:10–4:30 | `uv run forge budget` | "Paid API use is checked against the cap before every call; total spend $43.96 of $70." |
| 8 | 4:30–4:50 | `ls tasks/miniflux/` (10 tasks on a Go RSS server) | "Same pipeline on a Go repo: the factory is repo-agnostic. On a repo it had never seen, it produced 3 accepted tasks in 20 minutes." |
| 9 | 4:50–5:00 | repo URL | "Code, dataset and docs are MIT on GitHub." |

Numbers are from `reports/summary.json` (generated 2026-11-18); re-check them if the report is rebuilt. Never show
`.env`, API keys, or any employer name.
