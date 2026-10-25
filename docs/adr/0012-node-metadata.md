# ADR-0012 — Node metadata: an `about` note, separate from check descriptions

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-06-27)
- **Related:** [ADR-0007](0007-check-result-branches.md) (recursive `CheckResult` —
  descriptions on branch leaves), [ADR-0013](0013-check-config-on-node.md) (check
  config on the node), [ADR-0014](0014-maintenance-persistence.md) (the check-root
  coverage test the consistency pass shares),
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md) (the
  *About* card, the division of the two texts by what they say, a node's handbook and
  its details), [ADR-0018](0018-markdown-rendering.md) (the renderer),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope, which
  carries a node's texts raw),
  [ADR-0128](0128-where-a-nodes-first-look-comes-from.md) (the first look's keys, on
  the same addresses),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  (decision 8: a node's page, its facts after its children),
  [ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) (decision 2:
  the tags an entry writes, which add up with every other place that writes them).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
A node carries `description` + `frequency` inherited from its check (`project.md`
§2.1). Two gaps:

- **Nowhere to say what a node *is*** — a host's location, what kind of box, the
  context whoever is triaging would want.
- **`description` is overloaded.** A branch check like `host-metrics` would have to
  describe several leaves at once on the shared host node, and two checks targeting
  one host node (`nexus` runs `host-metrics` + `qnap-metrics`) would clobber it.

The awkward part is *where metadata comes from*: a leaf check owns exactly one node,
but **container / host nodes are often owned by no single check** — `system` is
auto-created by the tree, a host node is a neutral container its leaves roll up into.
"Put it on the check" cannot reach those. We also weighed describing the whole
system topology in one declarative YAML, but that recouples topology with check
config and can never be complete once a **satellite** grafts a remote branch at
runtime (`project.md` §2.9).

## Decision
Make node metadata a **property fed by several sources**, and split the two
concerns.

1. **`about` and `description` divide by what they say.** `description` says what the
   *check* reads or checks, in a sentence; `about` says where the thing stands, how to
   reach it and what to do — an instruction, in short, and not the node's kind and
   context at large. How to read a value is the description's or the handbook's, never
   the about's, so that the two never say one thing twice
   ([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
   decision 2). What a team writes at length about a node is its `handbook`, read on a
   tab of its own, and what it keys by name — whom to ask, where tickets go, a place —
   its `details` (ADR-0133 decisions 3 and 6).
2. **Sources, in precedence order:** a **`nodes.yaml`** declaration keyed by path
   (reaches container nodes no check owns, and satellite graft-points) **>** inline
   on the owning check **>** empty. A grafted satellite branch brings its own nodes'
   metadata in its JSON — the same node property, a third source. A node's `handbook`
   takes the same sources in the same precedence, and the `details` a deployment gives
   in the same two files hold for every node beneath their own, key by key, the nearest
   winning (ADR-0133). A `nodes.yaml` entry writes the node's `tags:` too
   ([ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision 2):
   a list of words, or one, which add up with what a check's file writes for the node
   and with every other root's entry for the path, no source winning, and hold for every
   node beneath. The same two files carry the keys of a node's first look on the
   same addresses — `chips`, `fold_ok` and `reason_cap`, and `children:`, under a path
   in `nodes.yaml` and under a subnode's name or at the top level of a check's file,
   which says them for each child of that node
   ([ADR-0128](0128-where-a-nodes-first-look-comes-from.md)). They are the web page's
   settings and never reach the node: the precedence above is `about`'s, and theirs is
   that record's. `nodes.yaml` is kept for the process's life.
3. **Per-leaf descriptions for branch checks.** A branch check declares each leaf's
   `description` through a `descriptions:` map keyed by leaf name (`disk`, `memory`,
   …); the shared host / container node's own `description` stays empty — which also
   stops two checks on one host node clobbering each other.
4. **Startup consistency pass.** After loading checks + `nodes.yaml`, **warn** for an
   `about` path that no configured check **covers** (an orphan — by the same
   static **check-root coverage** test the maintenance reaper uses, segment-wise on
   the same root-to-leaf line, [ADR-0014](0014-maintenance-persistence.md)), and
   info-log a host / container that has checks but no `about`. An entry that states
   only the first look's keys, or only tags, is a declaration, weighed like any other;
   a word under its `tags:` that is no tag is not read, the startup record naming it,
   the file still loading. Since an `about` is the node's short account, which its
   *About* card shows (ADR-0133 decision 1), the pass notes one past about 400
   characters, some four lines at a desk's width, and a `description` past about 160, a
   sentence; and it names a handbook's file that is missing or that nothing names, and
   a link into a handbook the node lacks or to a section it does not have (ADR-0133
   decisions 3 and 4). A config defect surfaces visibly, not as silent emptiness.
5. **Markdown.** `about` and the leaf descriptions are Markdown, rendered as every
   node text is ([ADR-0018](0018-markdown-rendering.md)).

## Consequences
- Every node can say what it is: its check's sentence in `description`, and where it
  stands and what to do in `about`, the two at any depth; and two checks on one host
  node stop colliding (decision 3).
- `about` reaches nodes no single check owns — the case per-check-only can't.
- A declared-but-unfed `about` is caught at startup, not left as a silent dead node;
  it simply shows `UNDEFINED` meanwhile.
- `nodes.yaml` is **optional** — the inline-on-check shortcut covers the
  one-check-per-node case with no extra file.
- Curated **links** are a page of their own, configured per deployment
  ([ADR-0030](0030-curated-links.md)): a node grows no `links:` field, and its own
  links ride in its Markdown and its details.
- The JSON envelope carries `about`, `title` and `description` as it carries every
  text of a node, raw ([ADR-0080](0080-the-envelope-is-the-snapshot-published.md)).
- **Where each field surfaces**: a node's `description`, `about` and details stand in
  its *About* card on its Status tab, beside its facts (ADR-0133 decision 1) — a
  branch's `description` too, which has stood beneath its row on its own page since the
  branch's head became the shared one — and the **inspection card**
  ([ADR-0019](0019-inspection-popover.md)) carries the first block of the `about`, or
  the `description` where there is no `about`, beside the name on the wall.
- **`about` is the short account of a node.** What a team writes at length about one —
  its runbook, how to sign in, its policy — is its handbook, which the `about` links
  into as `handbook#<section>`; whom to ask, where its tickets go and its
  documentation are its details.

## Alternatives considered
- **Per-check metadata only.** Lightest, but can't label container / system nodes
  (no owning check) and is ambiguous when two checks share a host node. Kept as the
  inline source, not the whole answer.
- **One declarative whole-system tree YAML** (topology + checks together). Rejected:
  recouples topology with check config, fights the per-deployment dir model
  ([ADR-0015](0015-check-discovery-union.md)) with big-file merge pain, and can never
  be complete once satellites graft branches at runtime.
- **Structured `links:` on the node**, for the `/links` page and the Swift client:
  declined by ADR-0030, which gave curated links a page of their own and left a node's
  own links in its texts; the links a team keeps of a node by name are its details
  (ADR-0133).
