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

## failure class: environment-scoped cache, queue and topic names

Several environments often share one cache cluster, broker or bucket. When a key, queue or topic name
is built without the deployment environment, or from a hardcoded default, staging writes overwrite
production entries and consumers pick up each other's jobs. The feature derives every such name from
one helper that takes the configured environment or namespace from the settings object, rejects an empty
or unknown environment with an error naming the setting, and makes the parts unambiguous (reject or
escape the separator). Attach to a real key, name or identifier this code builds; if it builds none,
add the helper next to the surface and route the existing name construction through it. Names for the
default environment the repo ships with must stay stable.

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
