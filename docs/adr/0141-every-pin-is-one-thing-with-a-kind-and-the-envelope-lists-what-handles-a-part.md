# ADR-0141 — Every pin is one thing with a kind, in one file, and the envelope lists what handles a part

- **Status:** Accepted
- **Date:** 2026-10-25
- **Related:** [ADR-0014](0014-maintenance-persistence.md) (the pin and its file —
  amended), [ADR-0036](0036-addressable-reasons.md) (a line's pin, which the file
  holds beside a node's — amended),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the directory the
  file is in — amended), [ADR-0134](0134-the-state-is-compressed-and-stamped.md) (the
  retired names, which `maintenance.json` joins — amended),
  [ADR-0077](0077-authority-follows-the-lease.md) (the takeover, which adopts the
  file), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope —
  amended, `schema_version` 3),
  [ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md) (the series read's
  golden answer — amended),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (a
  configured rule, which the envelope now lists),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (when a rule's block stands, which the list follows, and the envelope it kept —
  amended), [ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md)
  (who a request is, which now says what it may do — amended),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 7: a rule that cannot be read
  does not apply), [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) (a
  pin's note, which the file keeps under `note`),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) (*seen*,
  the first acknowledgment)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A person sets one thing on a failing part today: maintenance, which paints a node blue
and counts nothing of it. The maintenance-and-aggregation round gives them more — a
failure closed, a state seen, a flapping thing silenced — and each is the same kind of
thing: a target, a node or one of its lines; a note; who set it and when, and who first
did; an end. What differs by kind is what it does at the boundary, what ends it and what
it is bound to, a window in time or an occurrence. The line that splits files is current
state against archive — ADR-0047's argument for keeping the notes in a file of their
own — and every kind is current state. Several may stand on one target, two planned
windows on a node or a silence beside maintenance, so a pin needs a name of its own
beyond its target.

When the round was walked through, Lex settled that every kind is kept in one file in
place of `maintenance.json`, a break being no objection, and that every act a person
does with one has a permission named for it, every one an admin's until a deployment's
roles map onto them. At this slice's design pass, on 2026-10-25, he settled that the
envelope says every rule on a part in one list, and that the permissions take their
kinds' names.

This record is the first of two landings in one release: the file, the id, the
permission and the envelope, with maintenance the one kind there is. The acknowledgments
come in the second, as kinds of the same pin — *seen* in
[ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md).

## Decision

1. **Every pin is in one file, `pins.json`, a list of pins each beside its target.** A
   pin is its kind, its note, who set it last and when, who first did and when, until
   when where it has an end, and its id; its target is a node by its path, or one of its
   lines by the path and the line's slug, `slug` empty for the node's own. The file is
   `{"pins": [{"path", "slug", "id", "kind", …}, …]}` in the order of the targets, so
   the same pins are the same bytes, each time in UTC (ADR-0120). It is written
   through, carried by a keeper and adopted at a takeover as `maintenance.json` was.
   `maintenance.json` is not read: a start that finds it without `pins.json` says so
   once on its `load.` slug, at WARN, as a retired name of ADR-0134's — a pin set
   before the upgrade holds nothing until it is set again — and leaves it for a
   rollback. A file this release cannot read takes every pin with it, which fails
   toward alarming: a time without a zone, a path that is none, a pin without an id or
   a kind, or two pins of one kind on one place, which no kind allows yet. A pin of a
   kind this release does not know is skipped and named once — an older standby
   adopting a newer holder's file keeps every pin it understands (ADR-0032 rule 7), and
   its next write drops the rest.

2. **A pin has an id, made when it is first set and kept through every edit.** Sixteen
   random hex digits, which two pins never share in practice, and nothing to parse;
   clearing a pin and setting it again makes a new one, as its creation is new. The
   token a form carries back stays the pin's last write, `set_at` as it is spelled
   (ADR-0014 decision 8).

3. **The envelope lists what handles a part, and a contribution names the rule that
   decided: `schema_version` 3.** A node and an entry carry `handled`, what handles them
   now — a person's pin while it stands, and a configured rule while it changes what
   counts, on what a node passes up, on how its parent counts it among its children, or
   on how its children or its entries count in it — the predicate a rule's block on the
   wall follows (ADR-0135 decision 9). Each item has its `id`, its `kind` — the word
   `contribution.by` says it in — its `source`, `person` or `configuration`, its `note`,
   and `counts_as` in the notation `config/aggregation.yaml` writes a table in,
   `nothing` for a maintenance pin's part; a pin adds who set it and when, who first did
   and when it ends, null where it has no end, a configured rule its `file`, the day it
   stands `since`, its `level`, the lines or children it names and, with a count, how
   many fail. A `contribution` gains `rule`: the `id` of the item that decided, null for
   a mechanism — damping, a shield, a node not yet reported — and for a node that is
   maintenance because every one of its entries is pinned or its check said so.
   `maintenance`, the one object a pin had, goes: the spec is 3.0.0, the golden answers
   are `envelope-3.json` and `series-3.json`, and the macOS client takes
   `schema_version` 3 in the same release. Damping, the shield and *undefined* stay in
   `contribution.by` alone: no person set them and no file says them, and they draw no
   block.

4. **Every act has a permission of its own, named for the kind it sets.** A route asks
   `Identity.may(<name>)`, never `admin`, and every permission is an admin's until a
   deployment's roles map onto them — which makes that a mapping rather than a rewrite
   of every route. `maintenance` and `seen`
   ([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)) are
   the ones there are; `done` and `silenced` come with their kinds. Each act has a route
   of its own as well: a maintenance pin is set, changed and cleared at
   `POST /pins/maintenance`, a seen at `POST /pins/seen`, and `POST /maintenance` is
   gone, while `GET /maintenance` still redirects to *Handled* (ADR-0135 decision 8).

## Consequences

- An upgrade drops every pin that stands, its text with it: maintenance comes back where
  a person sets it again, and the start's line says so. A pin set after the upgrade
  enters its node's notes as it is set (ADR-0140), and its note stays there when the
  pin is gone.
- A client of the envelope that read `maintenance` reads the `maintenance` item of
  `handled`; one that walked `contribution` to a red root can name the rule beside its
  kind. The macOS client reads neither, so it moves by its supported version alone.
- `pins.py` takes the place of `maintenance.py`, and the tree's maintenance tables hold
  `Pin`s of kind `maintenance`; each acknowledgment of the second landing is a kind of
  the same pin, in the same file and on a route of its own.
- A configured rule is said by its name in the envelope, where only `aggregation` said
  it before, and its note and file with it: what the node's page and *Handled* say of
  it, a client can.

## Alternatives considered

- **`maintenance.json` kept, and a file beside it for the kinds that keep their part's
  true color**, or a file per kind — the first recommended, for sparing the pins that
  stand at this upgrade. Lex asked what is best for the architecture, a break being no
  objection, and one file is the model's own shape.
- **An `acknowledgment` object beside `maintenance` in the envelope**, additively at
  2.13.0 — recommended first, and asked again without regard to what came before: a
  field more with every job, where several rules may stand on one part and a configured
  rule was said by a word alone. **The same list beside `maintenance`, additively**,
  defers the same break and says maintenance twice until then.
- **Roles first**, as a slice of the round, or admins only with roles deciding every
  permission later: the first holds the round up for a question of its own, and the
  second leaves every route to be rewritten when it comes.

