# task families

A family is one recurring production failure class turned into a repeatable kind of feature task.
Each family lives in `families/<slug>/` with two files:

```
families/<slug>/
  family.yaml   # what the family is, which code it attaches to, which faults its tests inject
  prompt.md     # generator prompt for one (family, surface) pair, with placeholders
```

`incidentforge.families.load_family(slug)` parses `family.yaml` into a `Family` model (schema below) and
`render_prompt(family, ...)` fills `prompt.md` and appends the shared output contract
(`families/output-contract-<language>.md` when present, else `families/output-contract.md`), so every
family returns the same `TaskSpec` json shape. Family weights for sampling live in `families/taxonomy.json`.

## per-target profile

A target that is not a service (e.g. the click library) can carry `families/targets/<target>/`:

| file | effect |
|---|---|
| `profile.yaml` | `families` offered on the target, per-family `surface_kinds` order, `prefer` symbol regexes tried first (in order), `skip_symbols` never offered |
| `contract.md` | replaces the language output contract for that target |
| `<slug>.md` | appended to the family prompt as "how this failure class applies to <target>" |

`generate()` applies the profile in both the single-worker and the parallel path; a target without the
directory behaves exactly as before.

## `family.yaml` schema

| key | type | required | meaning |
|---|---|---|---|
| `slug` | str | yes | must equal the directory name, kebab-case |
| `title` | str | yes | short human title |
| `intent` | str | yes | what protection the feature adds, one or two sentences |
| `surface_kinds` | list[str] | yes | `Surface.kind`s this family attaches to (see below) |
| `fault_catalogue` | list[{id, description}] | yes, ≥2 | injectable faults; `id` is kebab-case and unique in the family |
| `acceptance` | list[str] | yes, ≥1 | criteria every generated task must meet |
| `difficulty_levers` | list[str] | yes | what makes a task in this family harder |
| `examples` | list[str] | yes, 1–2 | short, generic, not tied to any repo |
| `languages` | list[str] | no (`[python, go]`) | languages the family applies to |
| `map_rules` | list[rule] | yes for the failure map | which map nodes are exposed to this family (below) |

Surface kinds (`Surface.kind`): `settings-class`, `env-read`, `validator`, `consumer`, `cache-key`,
`config-writer`, `pool-config`. A language surface finder may add kinds; document them here when you do.

Example:

```yaml
slug: fail-fast-config
title: fail fast on missing or placeholder settings
intent: the service refuses to start when a required setting is missing, empty or a placeholder, and names every bad key in one error.
surface_kinds: [settings-class, env-read]
fault_catalogue:
  - id: missing
    description: a required setting is absent from the environment
  - id: placeholder
    description: a required setting still holds a placeholder such as "changethis"
acceptance:
  - startup raises one error that lists every invalid key, not just the first
difficulty_levers:
  - several settings with different rules must be validated together
examples:
  - an smtp host is required whenever email sending is enabled
```

## `map_rules` (failure map, `failmap/tag.py`)

A map node is exposed to a family when any of its rules matches; every condition in a rule must hold.
Parsed strictly by `failmap/tag.py` (unknown keys, kinds or non-scalar values are errors), not by `Family`.

| key | meaning |
|---|---|
| `id` | kebab-case, unique in the family |
| `node_kinds` | map node kinds: crg `File`, `Class`, `Function`, `Test`, `Type` or overlay `config_read`, `env_read`, `handler` |
| `surface_kinds` | the flat-scan `Surface.kind`s stamped on the node (any overlap matches) |
| `where` | `{attr: value}` equality on node attributes, e.g. `has_default`, `validated`, `typed`, `pool`, `parsed`, `dedupe`, `placeholder_default` |
| `name_matches` | optional regex searched in the node name |

A rule needs `node_kinds` or `surface_kinds`. Test nodes are never tagged.

## `prompt.md` placeholders

Write the family-specific guidance in plain markdown and use these placeholders; the renderer replaces
them with `{{name}}` syntax (no spaces). Unknown placeholders are an error.

| placeholder | filled with |
|---|---|
| `{{target}}` | target name, repo url, commit, language, test command and source root |
| `{{surface}}` | `file::symbol (kind)` of the surface the task attaches to |
| `{{excerpt}}` | the surface code excerpt (≤40 lines) |
| `{{faults}}` | the fault catalogue as a bullet list |
| `{{acceptance}}` | the acceptance criteria as a bullet list |
| `{{gold_example}}` | a complete accepted task (instruction, patch, tests) to imitate, or "none" |
| `{{previous_failure}}` | the failing gate and detail of the last attempt, or "none" on the first try |
| `{{existing_tasks}}` | titles of tasks already generated for this family and surface, or "none"; ask for a different behaviour |
| `{{task_id}}` | the task id the generator assigned, e.g. `fastapi-template/ff-003-smtp-settings` |

`families/prompt-template.md` is a starting point: copy it into a new family and edit the guidance part.
The output contract (json keys, unified-diff rules, test rules) is appended automatically; do not repeat it.
