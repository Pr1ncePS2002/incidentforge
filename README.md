# IncidentForge

A coding task factory for evaluating AI coding systems. It turns a working repository into
feature-development tasks whose requirements come from recurring production failure classes
(startup crashes on missing config, typed-config binding failures, impossible config windows,
stale hot-reload, environment-dependent keys, non-idempotent consumers, lossy config
regeneration, resource-blind defaults).

Every task ships in [Harbor](https://github.com/harbor-framework/harbor) format with a pinned
base commit, a reference solution, feature tests, fault-injection tests and regression checks,
and is accepted only after automatic validation.

> Work in progress — Innodata AI Hackathon 2026, Track 1 (Coding Task Factory).
