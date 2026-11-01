# ADR-0151 — A type states the keys its file takes, and any other stops the start

- **Status:** Accepted
- **Date:** 2026-10-31
- **Related:** [ADR-0131](0131-a-type-declares-what-it-grades-and-the-library-grades-it.md)
  (the declarations this one stands beside, and the keys a check's own gradings are
  written under, which the library adds — decision 2, the library's retired spellings,
  amended), [ADR-0128](0128-where-a-nodes-first-look-comes-from.md) (decision 7, a key
  the loader does not know — amended for a check's file),
  [ADR-0051](0051-what-startup-refuses.md) (decisions 2 and 3: the epoch, which moves on
  a documented behavior, and the refusal at import),
  [ADR-0086](0086-a-check-measures-and-grades.md) (decision 9: the last epoch that moved
  on a behavior, its nine types converting in the same change),
  [ADR-0049](0049-the-check-authoring-surface.md) (the surface this changes),
  [ADR-0025](0025-check-provided-subnode-metadata.md) (the `subnodes:` block the library
  reads for every type, and token substitution as a plain replace),
  [ADR-0023](0023-secret-references.md) (the `secrets:` block, which stays the type's),
  [ADR-0016](0016-node-addressing.md) (`name`, merged into `path`, whose refusal goes),
  little-sister-github ADR-0018 (§3: every aspect block refuses a key it does not take,
  the rule this carries to the top level)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check's file has two readers. The library reads the keys every check takes — `path`,
`frequency`, the `subnodes:` block and the rest, in `_parse_common` — and the keys the
gradings of the check's own block are written under
([ADR-0131](0131-a-type-declares-what-it-grades-and-the-library-grades-it.md)); the
type reads its own in `_extra_from_config`. A value either reader cannot take stops the
start, naming the file. A key neither reads did not: in the library's own blocks beneath
the top level, a `subnodes:` entry or a `children:` block, it was one line in the log
([ADR-0128](0128-where-a-nodes-first-look-comes-from.md) decision 7), and at the top
level it was nothing at all, since the rest of the top level was the type's and the
library could not judge it. So `frequncy: 5m` loaded without a word and the check ran
at the default frequency, and a key a type had retired was read by nobody and stopped
nothing.

The family carries no code for an old spelling, on Lex's word of 2026-10-31: a retired
key breaks a configuration that still writes it by the refusal any unknown key meets.
That held inside the blocks that refuse a key they do not take — little-sister-github's
and little-sister-aws's aspect blocks, a `secrets:` block, a value under a pair's bare
key — and nowhere at the top level, where each retirement kept a refusal of its own:
here `thresholds:` in `host-metrics`, `macos-memory` and `qnap-metrics`, the `file`
check's `max_age` with a level and its `stale_code`, and `name`; in little-sister-github
`org:`, a `code_scanning_alerts:` block, `expect_min_repos`, and `github-rate-limit`'s
`warn_below` and `error_below`. Two more stood in entries that took any key at all, a
`macos-memory` process and a `github-rate-limit` resource, and one in a label's text,
`{org}`, which substitution leaves standing.

The design round with Lex of 2026-10-31 settled what follows, six questions one at a
time; what each declined is under *Alternatives considered*.

## Decision

### 1. A type states the keys its file takes, beside what it grades

A type hands `Check.__init__` the keys it takes at the top level of its file —
`config_keys`, a list of names, its blocks among them — beside its gradings, its forms,
its words and its fields. It names only its own: the library adds the keys every check
takes (decision 2) and those the gradings of the check's own block are written under,
the library's window among them, so a type restates neither, and a list that names one
of them is refused when the check is built, as a type's form under a name the library
writes from is (ADR-0131 decision 7). A type that states nothing takes nothing of its
own. What a type's own block takes stays the type's to say and to refuse.

### 2. The library names the keys every check takes in one list

`COMMON_KEYS`, beside the reader that takes them: `type`, which the loader reads, and
every key `_parse_common` reads — the node's labels, details and tags, its rank and its
claim, the first look's keys and `children:`, `subnodes:`, the schedule, the retry, the
escalation and the dependency, the series and its measures, the reading cap and
`display:`. A test hands the reader a mapping that records each key it looks up and
holds what it read to the list both ways, so that a key it comes to read joins the list
in the change that reads it, and one it stops reading leaves it. `secrets:` is not on
it: the library's reader takes the block ([ADR-0023](0023-secret-references.md)), but
only a type that calls it takes one, and that type states it — on any other type a
`secrets:` block would load and do nothing.

### 3. Any other key stops the start, wherever the library reads

At the top level, in a `subnodes:` entry and in a `children:` block, a key that neither
the library nor the type takes refuses the start as the check is built, naming the file,
each such key and what its place takes — at the top level the type's keys, its
gradings' and every check's — in the shape the family's blocks refuse in. ADR-0128
decision 7's line in the log becomes this refusal in a check's file; `nodes.yaml`,
`settings.yaml` and a type's declarations keep theirs.

### 4. A retired key needs no code

A type that retires a key leaves it out of `config_keys`, and a configuration that still
writes it stops the start by decision 3's refusal, naming what the type takes now: no
message of its own, and no release of warnings before it. The library's code for its old
spellings goes: `thresholds:` of `host-metrics`, `macos-memory` and `qnap-metrics`, the
`file` check's `stale_code` and its `max_age` with a level — which the pair's bare key
refuses, as it refuses any value but null — and `name`, merged into `path`
([ADR-0016](0016-node-addressing.md)). A `macos-memory` process entry refuses a key that
is not its `name`, its `pattern` or its pair's, so that a retired `warn_mb` or
`error_mb` meets the same refusal. Substitution stays a plain replace of the tokens a
type declares ([ADR-0025](0025-check-provided-subnode-metadata.md)), so a token a type
retires shows as written wherever its text is read.

### 5. This is a new epoch, 4

Stating its keys is required of every type, a documented behavior of the surface
([ADR-0051](0051-what-startup-refuses.md) decision 2), so the check API epoch moves to
**4**, and the nine types this library registers state theirs in the same change —
`command`, `file`, `http`, `ssh-command`, `ssh-connect`, `ssh-script`, `host-metrics`,
`macos-memory` and `qnap-metrics`. A package built for 3 refuses at import, naming both
numbers. Every package that declares the epoch moves with it and is released with the
library, raising its floor to it: `little-sister-github`, `little-sister-aws`,
`little-sister-wiz` and `little-sister-jira`, which registers no type and declares the
epoch all the same, since the epoch versions the whole surface.

## Consequences

- **A breaking change for configurations.** A file that writes a top-level key nothing
  takes — a typo, or a key retired before this release — stops the start, naming the
  file and the key; so does an unknown key in a `subnodes:` entry or a `children:`
  block, which a line in the log said before. The release notes say it at the top.
- **A breaking change for types.** Every type states its keys and declares epoch 4, and
  every package is released with the library. A deployment that pins takes all its pins
  at once, and a type it keeps of its own states its keys in the same change.
- **A key read and not stated** stops the start of every configuration that writes it,
  which a type's tests meet first by loading its example through the loader, since an
  example writes every key. **A key stated after its reader has gone** is the one case
  nothing refuses, and a type's tests hold it.
- **One list of what every check takes**, held to its reader, which the refusal quotes
  and the how-to names.
- **No code for an old spelling**, here or in a package: a refusal no longer works out
  the replacement from the levels a configuration wrote.

## Alternatives considered

- **The keys derived from what construction reads**, through a mapping that records each
  key looked up: no list to keep, but it counts a look and not a use — a key read to be
  refused, `"secrets" in config`, a helper handed the whole mapping — calls a key a type
  reads on one branch of its configuration unknown on the other, holds only while every
  reader goes through the recorded methods, and cannot show what a type takes without
  building one. **The same names as a class attribute** `from_config` reads, which
  `/system/installed` could list unbuilt: the refusal still waits for the gradings' keys,
  known in `__init__` alone, and it would be the one declaration not handed there.
- **A table-driven `_parse_common`** whose table is the list: a rewrite for a list, and
  its keys do not map one to one onto what it hands a check — `subnodes:` feeds five
  keywords, the first look is read from four keys. **The list derived from what the
  reader reads on each file**: a mechanism run on every load for a set that never
  changes, in which `name` reads as taken. **`secrets:` among every check's keys**, which
  leaves the block doing nothing on a type that takes no credential.
- **The warnings beneath the top level kept**, the top level alone refusing: two rules in
  one file, `titel:` stopping the start where `subnodes.actions.titel:` writes a line,
  and a key retired from an entry needing code of its own again. **A warning at the top
  level too**: a retired key warns where the family decided it breaks.
- **The statement optional**, a type that states nothing judged as before and the epoch
  staying: the rule would hold only where a type states, a typo at the top of any other
  file still silent, and nothing saying which types those are. **Optional, with the types
  that state nothing named** on `/system/installed`: a surface built for a gap of one
  type, a deployment's own.
- **The library's refusals of its old spellings kept**, a precise answer with the levels
  a configuration wrote for whoever upgrades across them, as the one exception; and **the
  top level's dropped and the process entry's kept**, which needs no new refusal but
  leaves code for an old spelling in the one place a block took any key.
- **A `{token}` nothing declares refused at load**, the same pattern again: braces are
  legitimate in a label's text — the status signs, `{default}`, a handbook's code — so
  which text is read and which braces count is a design of its own.
