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

## failure class: config load, modify, save never drops a field

Tools that read a configuration or a settings record, change one field and write it back often lose data:
fields the writer does not know are dropped, explicit values equal to the default or explicitly empty
values are omitted and later re-read as something else, types drift (a duration becomes a plain number),
and a failed save leaves a truncated record. The feature makes the round trip lossless: load then save
with no change is a no-op, changing one field changes only that field, unset and explicitly empty stay
distinguishable, and a failed save keeps the previous record. Attach to a real serialiser, form or
settings writer on this surface; if the surface only reads, add the matching writer for the same record.

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
