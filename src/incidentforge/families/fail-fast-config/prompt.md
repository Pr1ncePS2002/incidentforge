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

## failure class: fail fast on missing or placeholder settings

Services often start with a required setting missing, blank or still holding a template placeholder, run
fine for a while, then fail on the first request that needs the value. The feature makes the service refuse
to start instead: settings construction checks the required values and raises one error that names every
bad key. Pick settings from this surface that the code really uses; keep valid shipped defaults loading.

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
