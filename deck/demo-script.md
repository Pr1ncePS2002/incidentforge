# Demo video script (3–5 min)

Record in one terminal (large font, dark theme) plus a browser for the report and the map. Run steps 2, 3 and 6
once before recording so images and the map are cached; generation can be sped up in editing (say so on screen).

| # | Time | Show on screen | Say |
|---|---|---|---|
| 1 | 0:00–0:25 | README top, families table | "AI coding benchmarks test the happy path. Real outages come from a few recurring failure classes. IncidentForge turns any repo into tasks built from those classes, each with fault-injection tests." |
| 2 | 0:25–1:00 | `uv run forge map build --target fastapi-template --coverage`, then open `reports/map.html` and click a red-ringed node | "First it maps the repo: a code graph where each node is tagged with the failure families that fit it, sized by blast radius. A real test run marks what the repo's own tests never touch — the red rings — and those go first." |
| 3 | 1:00–1:40 | `uv run forge run --target fastapi-template --n 8 --workers 4` (sped up) | "Clusters share no file, so four workers generate in parallel under one cap of Docker containers. Each candidate then faces six gates before we keep it." Point at gate lines as they print. |
| 4 | 1:40–2:15 | `ls tasks/fastapi-template/ff-001-email-config/`, then `cat` its `instruction.md` and `tests/feature/tests/test_forge_email_config.py` | "This is a Harbor task: the instruction the agent sees, the reference patch, and tests that inject the failure. Here, a mail host is set without a sender address." |
| 5 | 2:15–2:35 | `cat reports/validation/fastapi-template/ff-001-email-config.json` | "Every gate is logged: fails on the base commit, passes with the reference, repo suite green, mutants killed, no leak, three stable reruns." |
| 6 | 2:35–3:00 | `harbor run -p tasks/fastapi-template/ff-001-email-config -a oracle`, then `-a nop` | "Harbor confirms it: the reference solution scores 1.0, doing nothing scores 0.0. CI re-checks every task this way before release." |
| 7 | 3:00–3:50 | open the live report (Pages URL), results then "why models fail" | "52 tasks, 8 families, a Python and a Go repo; every task passed all gates and the tests killed 89% of 309 mutants. Harbor's Claude Code agent passes CC_RATE. Gemini 2.5 Flash and 3.8 Flash through terminus-2 pass G25_RATE and G38_RATE; the agents differ, so compare within one agent. Every failed run gets exactly one cause: most ran out of turns, and the next biggest group passed the normal cases but missed an injected fault." |
| 8 | 3:50–4:15 | `grep source_url tasks/fastapi-template/ff-005-create-engine-7/task.toml`, then its `instruction.md` | "Tasks can also start from a real postmortem: this one comes from a public AWS incident report. The classifier picks the family, the map picks where it lands, the same gates decide." |
| 9 | 4:15–4:40 | `ls tasks/miniflux/` (19 tasks on a Go RSS server) | "Same pipeline on a Go repo: the factory is repo-agnostic. On a repo it had never seen, it produced 3 accepted tasks in 20 minutes." |
| 10 | 4:40–4:50 | repo URL and Pages URL | "Code, dataset, report and map are MIT on GitHub, and the report is live on Pages." |

Numbers are from `reports/summary.json`; re-check them if the report is rebuilt. Never show `.env`, API keys,
or any employer name.
