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

## failure class: dynamic settings take effect without a restart

Operators change a value at runtime (a timeout, a rate, a feature switch) and expect the next call to use
it. The outage happens when some code copied the value once, at import, at package init or in a
constructor, and keeps serving the stale copy until a redeploy. The feature adds an explicit reload path
(a `reload`/`apply` function that takes new raw values) and makes every reader go through one accessor
that returns the current value. A reload with an invalid value must be rejected and the last good value
kept; related values must swap together. Keep the behaviour without any reload exactly as it is today.
In Go, the accessor must be safe for concurrent readers (atomic value or a mutex); avoid data races and
sleeps in tests.

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
