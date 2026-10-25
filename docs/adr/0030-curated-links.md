# ADR-0030 — Curated links come from a deployment-supplied file

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-08-01)
- **Related:** [ADR-0031](0031-deployment-config-directory.md) (the `config/` directory
  and its layering, which this file is an aspect of),
  [ADR-0015](0015-check-discovery-union.md) (the path-list underneath it),
  [ADR-0012](0012-node-metadata.md) (`nodes.yaml` — the precedent for a non-check YAML
  beside the checks), [ADR-0021](0021-script-resolution.md) (packaged defaults with an
  override — the shape the icon packs copy), [ADR-0018](0018-markdown-rendering.md) (the
  renderer, and images-on),
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md) (a
  node's handbook and its details, which hold its runbook and its own links),
  [ADR-0028](0028-design-tokens-and-themes.md) (themes the icons must survive),
  [ADR-0029](0029-per-user-presentation-preferences.md) (`DARK_THEMES` → `bs_theme`, the
  seam the icon variants ride), [ADR-0048](0048-an-assembled-content-security-policy.md)
  (decision 4: the page's own policy allows the hosts its icons load from).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
`/links` has been a placeholder since the route existed: a heading and a sentence about
the capybara on call. The use case it answers is narrow and worth stating precisely —
somebody is firefighting, and wants the two or three dashboards and tools that matter
for what is on fire, immediately, without hunting through a wiki
([`use-cases.md`](../use-cases.md) §6).

Three facts constrain the design more than they first appear.

**The content is not ours.** little-sister is a library; the links belong to the
deployment that installs it. Checks already arrive that way — a path-list of directories,
unioned in order ([ADR-0015](0015-check-discovery-union.md)) — and `nodes.yaml` already
established that a *non-check* YAML may share that directory. Any new mechanism that
does not reuse this is a second way to do the same thing. Being the third tenant of a
directory named `checks/` is what prompted
[ADR-0031](0031-deployment-config-directory.md); this file is an **aspect** of the
`config/` directory defined there, and inherits its layering.

**Runbooks are already elsewhere.** A check carries its own `description` and `about`
([ADR-0012](0012-node-metadata.md), [ADR-0013](0013-check-config-on-node.md),
[ADR-0025](0025-check-provided-subnode-metadata.md)), and a node's runbook is its
`handbook`, from the same sources
([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)), next
to the thing that fails. So this page is **general helpers** — the shared Grafana, the
ticket queue, the team's toolbox — not per-node documentation. That removes the
temptation to design a link record rich enough to also hang off a status node.

**A restart is expensive.** Status history is derived from an in-memory
`deque` and does not survive the process ([ADR-0001](0001-in-process-threaded-engine.md);
durable history waits for the persistence phase). Anything that makes editing a link
list cost a restart costs the operator their incident history — an absurd price for
fixing a URL.

The shape this page takes in the wild is well established: one flat level of categories
laid out in columns, each entry a small application icon plus a title, and a filter box
above them because the list grows to fifty or sixty entries. The failure mode is equally
well established — the icons rot. A reference implementation we looked at was showing
three broken-image glyphs, all of them internal hosts.

## Decision

**A deployment supplies `links.yaml`; little-sister owns how it looks.**

1. **Links are a `config/` aspect.** One optional `config/links.yaml` per root of
   `LITTLE_SISTER_CONFIG_DIR` ([ADR-0031](0031-deployment-config-directory.md)) — or
   `config/links/` once a deployment ships icon files of its own — so a deployment that
   already composes `base:sites/alpha` gets link layering for free.

   **With no links the page opens with one sentence** — what the page is, and that it
   has not been filled in — and holds its setup guide in two folds, each the browser's
   own disclosure and closed: *Add links*, the file's shape and where it goes, and
   *Icon names*, the roster and how a deployment adds a mark of its own (decision 3).
   The guide in full — a sample file, where it goes, every name of the registry with
   both its drawings, and how to add a mark — is more than a screen before anybody has
   a link. Every reader gets the same page, the file's path included: the page knows
   no roles, because whoever maintains the file is not necessarily an admin.

2. **One level of grouping, merged by title, in file order.** Groups with the same
   title across directories **concatenate**, base first, so a site can add entries to a
   shared group. This deliberately differs from the checks loader, which hard-errors on
   overlap ([ADR-0015](0015-check-discovery-union.md)): two checks claiming one node is
   an ambiguity about *truth*, two files contributing to one group is not. Entry order
   is **curated and preserved — never sorted**; an operator who puts *EMERGENCY STOP*
   first means it.

3. **Icons are referenced by name, and the names aggregate.** An entry says
   `icon: grafana`; it never carries a URL. The same application appears many times on a
   real page, so a dozen Grafana links cost **one** icon — one definition, one fetch. A name resolves through a search path, first match wins, in the shape
   [ADR-0021](0021-script-resolution.md) already uses for scripts:

   1. the deployment's own `icons:` map — a remote URL, or a file beside the config;
   2. **icon packs registered by dependent packages**, later registration winning, so a
      house library of company-internal marks reaches every deployment that installs it;
   3. **little-sister's built-in pack** — the DevOps marks nearly every deployment links
      to, shipped as package data and served from our own origin, so the common case needs
      **no configuration and makes no outbound request**. The roster is fixed and
      deliberately short: `grafana`, `prometheus`, `jenkins`, `github`, `gitlab`,
      `kibana`, `elastic`, `jira`, `confluence`, `keycloak`, `docker`, `kubernetes`,
      `argo`, `sonar`, `nexus`, `pagerduty`, `aws`. The pack carries **only marks we may
      redistribute**, which is a per-mark question answered before a file lands and
      recorded in the pack's manifest. A name whose file we may not ship still **exists**
      — it simply falls through to steps 4 and 5;
   4. the link origin's `/favicon.ico`;
   5. a neutral inline SVG.

   The search path has one further rung. **`config/links/icons/` is the deployment's
   own pack, discovered by file name** — dropping `firewall.png` there and writing
   `icon: firewall` is the whole of it, with no `icons:` entry. The pair convention is
   the built-in pack's own file names (`<name>-on-light.*` / `<name>-on-dark.*`);
   anything else is a single file on the chip; one flat directory, no recursion; a
   non-icon file (a README, a `.DS_Store`) passes in silence. It sits **above** the
   packs a dependent package registers and **below** the `icons:` map, which stays the
   way to say what a file cannot — a remote URL, or `none`. Order across roots is
   unchanged: later root wins, per name, whole.

   The reason is a real port. A deployment moving sixty links off an older tool put its
   seven own marks into `config/links/icons/`, wrote `icon: firewall` beside the
   entries, and was told *no icon named 'firewall'* while the file sat in the directory
   the page was reading. Requiring a second declaration for a file already named after
   the thing it draws is a rule with no reader, which is why *"a name resolves through a
   search path"* reaches the deployment's own directory too. Only the **directory** form
   has one, which is what that form is for
   ([ADR-0031](0031-deployment-config-directory.md) §2): an `icons/` beside a flat
   `config/links.yaml` is a directory in a configuration root, and warns as an
   unrecognized aspect rather than being read as ours.

   A packaged icon is a small SVG, and may itself be an `on_light` / `on_dark` pair —
   GitHub's mark is exactly why. An icon never renders as a browser's broken-image glyph.

   **Filling a name we may not ship**, in the order we prefer: **draw our own generic
   glyph** (a cloud for `aws`, a git glyph for `github`) — no trademark question, no
   redistribution question, works offline, and it themes as a proper pair, at the cost of
   recognizability; then **the deployment's own local file**, which puts the mark under the
   operator's legal posture and is the natural answer for a company already running the
   product; and only then **an external URL**, which settles redistribution but is the
   least reliable of the three.

   **Overriding a built-in.** Resolution is **per name, not per pack** — for each name
   independently, the highest-precedence pack that defines it wins, so a house pack
   defining only `aws` leaves the other sixteen built-ins standing. An entry **replaces
   whole**: a deployment supplying only a dark file for `github` replaces the built-in pair
   outright rather than filling in half of it, because merging variants across layers is
   the rule that produces *"why is my light icon still the old one"*. A name may resolve to
   **nothing** — `aws: none` is a legal entry meaning *do not display this mark*, falling
   through to steps 4 and 5; without it a built-in could be swapped but never turned off,
   which is exactly the case the redistribution question raises. And when one pack shadows
   another's name the loader **logs it**, naming winner and loser: two packages both
   registering `grafana` otherwise resolve by import order, which nobody should have to
   reason about silently.

   **The names stay within reach of a page that has links**, which keeps decision 1's
   *Icon names* fold closed at its foot, under the links and outside what the filter
   narrows. A deployment that has written its file would otherwise lose the roster
   with the empty state, and adding a fortieth link would mean guessing a name or
   reading the log.

4. **An icon may declare a light/dark pair, and the pair is chosen in CSS.** A brand
   logo does not theme: a black mark vanishes on the dark themes and a white one
   vanishes on the light. An icon may therefore be a mapping of `on_light:` / `on_dark:`
   — named for *the background it goes on*, not for the color of the file. Both are
   emitted and one is hidden by `body[data-bs-theme="dark"]`, which
   [ADR-0029](0029-per-user-presentation-preferences.md) already sets for every dark
   theme server-side **and** for `auto` via the pre-paint script. The choice cannot be
   made in Jinja: under `auto` the server does not know what the OS will resolve to.
   An icon with **no** pair renders on a **theme-invariant light chip**, so a
   single-file logo is legible in every theme; an icon **with** a pair renders bare,
   since it has already solved the problem itself. The chip is the floor, the pair is
   the upgrade.

5. **Links on a node stay prose — this page does not change node metadata.** A node's
   `about` and `description` are Markdown ([ADR-0018](0018-markdown-rendering.md)) and
   already carry links. Its runbook is its `handbook`
   ([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)),
   from the `about`'s sources — a type ships its reference once, and a deployment writes
   its own around it with `{default}` ([ADR-0013](0013-check-config-on-node.md),
   [ADR-0025](0025-check-provided-subnode-metadata.md)) — read on a tab of its own and
   linked from the node's texts as `handbook#<section>`; and what a team keeps of a node
   by name — its console, its board, whom to ask — is its `details`, each a line of
   Markdown that may hold a link. Those are fields of the node's own, and the contract
   changed with them — a status-model field, a JSON contract change and an
   `openapi.yaml` bump — but for what a team says of a node at length and by name. A
   node grows no `links:` list: a link on a node stays prose, in its texts and its
   details, and a second, typed channel for it is not worth that cost. The two surfaces
   stay separate: **this page is general helpers, the node knows its own subject.**

6. **An entry may carry one line of Markdown.** `note:` renders inline and muted under
   the title — room for *"page the ISP before touching this"*. No page introduction, no
   group prose: the runbooks are the nodes' handbooks, and this page is a launcher.

7. **The file is re-read when its mtime changes**, not loaded once at startup. A
   `stat()` per request, a parse only when the file actually changed. Editing links must
   not cost a restart, for the reason given in the context.

8. **The file is validated at load, offline.** Its checks — schema, unknown icon name,
   duplicate titles within a group, a rejected URL scheme — run **at load**: instant,
   warn-and-continue, in the spirit of the `nodes.yaml` consistency pass
   ([ADR-0012](0012-node-metadata.md)). A key the file does not have is reported as such
   — a `check:` block or an entry's `check:` among them, left from when the page probed
   its entries (*Alternatives considered*) — and the entry it sits on is still shown.
   Nothing asks whether a link or an icon answers: a dead link is found by clicking it
   and fixed in the file, and a tool whose availability matters is a node, through an
   `http` check, with the pins, the history and the strip that come with one.

Local icon files make this aspect a **directory**, so the example below is
`config/links/links.yaml` with its files in `config/links/icons/`. A flat
`config/links.yaml` beside a sibling `config/icons/` is *not* the same arrangement and
does not work: `icons` is not an aspect, so it warns as unrecognized and is ignored
([ADR-0031](0031-deployment-config-directory.md) §3). A deployment whose icons are all
built-in or remote URLs needs no directory and can stay flat.

```yaml
# config/links/links.yaml   (icon files live in config/links/icons/)
icons:
  # grafana, prometheus, jenkins, github … need no entry — they are built in.
  phoenix: icons/phoenix.svg                           # single file → on the chip
  backstage:                                           # a pair → rendered bare
    on_light: icons/backstage.svg
    on_dark:  icons/backstage-inverted.svg
  jenkins: https://ci.example.org/favicon.ico          # overrides the built-in

groups:
  - title: Toolbox
    links:
      - title: Cyber Chef
        url: https://gchq.github.io/CyberChef/
        icon: cyberchef
        note: offline-capable, safe for production data
```

## Consequences
- A deployment fills the page with one file in a directory it already points at, and
  gets base-plus-site layering without a second mechanism.
- **The presentation stays in the library**, so the page inherits the themes, the rail,
  the kiosk layout and the band without a deployment having to know they exist. A
  free-Markdown page would have opted out of all of it.
- Entries are **records**, so the filter box is a one-line client-side match on **the
  entry's title and its group's** rather than a search over rendered prose. Still
  titles, never prose. Measured on the first real page rather than reasoned about: with
  entry titles alone, typing a category name (`loadtest`) matched nothing at all, which
  reads as a broken page rather than as a narrow rule, and typing the category is
  exactly what somebody who knows the toolbox does. `note:` stays out, for the reason
  the decision gives for making entries records at all: a note is prose, and a match the
  reader cannot see in the title it landed on is the failure mode records were chosen to
  avoid. Tokens match with **and**, in any order, so a second word narrows. Order is
  untouched — the filter hides, it never sorts.
- **Nothing measures the links**, so a moved Confluence page never turns the dashboard
  amber for everyone, and the instance asks no host anything for this page.
- **The built-in pack makes the common page zero-configuration**, and a page built only
  from built-in and local icons makes **no outbound request at all**. Remote URLs remain
  possible, with the tradeoff [ADR-0018](0018-markdown-rendering.md) already accepted for
  images — the difference being that these are operator-curated rather than embedded in
  prose. **Caching remote icons locally is explicitly not planned**: the pack removes
  most of the need, and a cache means a writable directory, an invalidation rule and a
  fetch path for a problem a deployment can solve by adding one file.
- **The pack's roster is bounded by redistribution, not by usefulness.** Using a
  product's mark to identify a link *to that product* is ordinary nominative use, but
  redistributing the file inside a wheel is a separate question, and some vendors answer it
  restrictively. So the pack ships only what it may ship, carries a manifest naming each
  file's source and terms, and lets the two escape hatches cover the rest — a
  redistributable alternative, or an external URL in the deployment's own `icons:` map.
  A missing name costs one line of config; a mark we should not have shipped costs more.
- **Hotlinking answers one of three questions, not all of them.** Pointing at a vendor's
  own file removes the **redistribution** question, since nothing is copied into the wheel.
  It leaves **trademark** exactly where it was — nominative use, a mark labeling a link to
  that very product, is what makes the page fine either way. And it adds a **terms of
  service** question, because plenty of asset hosts forbid hotlinking as a bandwidth matter
  and enforce it with a `403`. It also trades a licensing problem for a reliability one:
  referrer-based hotlink protection, URLs that rot on a vendor redesign, and no icons at
  all for a deployment without outbound access. Hence the preferred order in the
  decision.
- **A remote icon is fetched by the viewer's browser, never by the instance.** The hosts
  a remote mark or a fallback favicon loads from are allowed by the page's own
  Content-Security-Policy, taken from this file as the page renders
  ([ADR-0048](0048-an-assembled-content-security-policy.md) decision 4), so none needs a
  line in `config/csp.yaml`. That the browser fetches them is deliberate: the page
  exists to send the viewer to those sites, so a browser that can open a link can fetch
  its icon, and one that cannot has no use for the link either — while the instance may
  stand where those hosts are out of its reach. A favicon that redirects to a host the
  file does not name, a login wall's, is still reported, and an enforced policy draws
  the neutral glyph for it.
- The `onerror` fallback to the neutral glyph must be an **external listener**, not an
  inline attribute, so the page does not become the reason a Content-Security-Policy
  cannot be turned on.

## Alternatives considered
- **A generic Markdown page** — render whatever the deployment writes, one nav entry,
  wiki-like. Cheapest to build and infinitely flexible, and it reuses the existing
  renderer. Rejected: it opts out of the design system, cannot be filtered, and "one
  menu entry" honestly means an index plus subpages plus slugs — a wiki, which is not
  what a monitoring tool should grow. Markdown survives as the `note:` field.
- **An icon URL on every entry.** One less indirection and a flatter schema, but the
  same URL repeats on every entry of an application, and the fetch multiplies with it.
- **Auto-favicon only, no icon field.** Zero configuration, and it is visibly what the
  reference implementation does — including the three broken glyphs, because internal
  hosts often serve no favicon and there is no way to override. Kept as the *fallback*,
  rejected as the *mechanism*.
- **No built-in pack — every deployment names its own icons.** Carries no marks and no
  licensing question, but makes every installation re-solve the same problem for the same
  ten products, and pushes each of them onto a remote URL that can rot. Rejected for the
  reason [ADR-0021](0021-script-resolution.md) gave about scripts: a packaged default is
  what keeps the built-in case zero-configuration.
- **Two levels of category.** Rejected: nesting is navigation, and the reader is
  mid-incident. If one level ever stops being enough, that is evidence the deployment
  wants a wiki, not that this page wants a deeper tree.
- **Probing the entries**, as the page once did: icons by default and links per entry,
  on a pass an open of the page set off once its answers were six hours old, each
  verdict beside its entry and none on the status tree, and a *check now* that waited
  for the answer. No deployment had switched a link on, so what a pass asked was a
  handful of remote icons, whose failure the neutral glyph already absorbs, and the
  answer cost a module of its own, a pass deadline and threads a host could keep.
  Probing at startup had been rejected already, for slowing boot and needing the network
  at the worst possible moment, and a pass every n-th open for being unpredictable in
  both directions.
- **A `links` check type configured deployment-side**, measuring the links as nodes:
  links are not infrastructure and have no honest node in a deployment's tree, so the
  placement would be arbitrary in every installation. A tool whose availability matters
  is a node already, through an `http` check.
- **Loading once at startup**, consistent with the checks. Rejected for what a restart
  costs while history is in memory.
