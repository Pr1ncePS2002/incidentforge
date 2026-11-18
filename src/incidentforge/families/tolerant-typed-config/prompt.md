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

## failure class: typed settings reject what operators actually write

A config change is rolled out with a list as `a,b,c` instead of a json array, a flag as `yes`, or a
timeout as `30s`, and the typed binding crashes the service at startup with an unreadable parser trace.
The feature makes the settings accept the realistic spellings and turn them into the same typed value,
while genuinely bad input fails with a clear message that names the key and the bad value. You may add
a new setting when the surface has none of the right type, as long as the feature is real and used.

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
