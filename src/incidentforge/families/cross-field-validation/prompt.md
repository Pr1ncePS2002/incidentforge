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

## failure class: impossible combinations accepted silently

Each field is valid on its own, but together they cannot work: a window ending before it starts, a
minimum above its maximum, a per-try timeout longer than the whole deadline, two exclusive modes both on.
The system accepts it and misbehaves much later. The feature rejects the combination at validation time
with an error naming both fields. State the equal-values boundary rule in the instruction.

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
