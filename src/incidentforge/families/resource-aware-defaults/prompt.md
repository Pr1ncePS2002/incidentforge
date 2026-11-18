You are writing one feature-development task for a coding benchmark. The task asks an engineer to add a
protection that stops a known class of production failure. You write the task statement, the reference
solution and the hidden tests.

## target

{{target}}

## where the task attaches

Surface: {{surface}}

```
{{excerpt}}
```

## failure class: pool and worker sizes derive from configured limits

Hardcoded pool, worker, batch or buffer sizes work on a developer laptop and fail in production: a pool
larger than the database's connection limit, more workers than cpus, a minimum above a maximum, or a
size of zero that deadlocks. The feature derives the size from the configured limits with a documented
formula, falls back to a safe default when a limit is unset, and rejects impossible combinations at
startup with one error naming both settings. Use the real pool/worker/batch settings this surface
exposes; keep the shipped defaults loading and the derived value actually used where the size is consumed.

Faults the hidden tests must inject (cover at least two):

{{faults}}

Every task must meet:

{{acceptance}}

## example of an accepted task

{{gold_example}}

## tasks already generated here (pick a different behaviour)

{{existing_tasks}}

## previous attempt

{{previous_failure}}

Task id: {{task_id}}
