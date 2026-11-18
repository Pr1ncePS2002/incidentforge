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

## failure class: handlers that double-apply on retry

Queues redeliver, clients retry on timeout, and jobs restart after a crash. A handler that is not
idempotent then creates duplicate rows, sends a second email or increments a counter twice. The feature
makes the handler safe to run twice: define how the idempotency key is derived (an explicit request id or
a stable key from the payload), apply the effect once, and return the original result on a repeat. Call the
handler directly in tests (a function call or the app's test client), not over the network.

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
