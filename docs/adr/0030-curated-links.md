# ADR-0030 — Curated links come from a deployment-supplied file

- **Status:** Accepted
- **Date:** 2026-07-31
- **Related:** [ADR-0031](0031-deployment-config-directory.md) (the `config/` directory
  and its layering, which this file is an aspect of),
  [ADR-0015](0015-check-discovery-union.md) (the path-list underneath it),
  [ADR-0012](0012-node-metadata.md) (`nodes.yaml` — the precedent for a
  non-check YAML beside the checks), [ADR-0021](0021-script-resolution.md) (packaged
  defaults with an override — the shape the icon packs copy),
  [ADR-0018](0018-markdown-rendering.md) (the
  renderer, and images-on), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (the reserved `/little-sister` line), [ADR-0024](0024-dashboard-layout.md) (the status
  strip this deliberately does not disturb),
  [ADR-0028](0028-design-tokens-and-themes.md) (themes the icons must survive),
  [ADR-0029](0029-per-user-presentation-preferences.md) (`DARK_THEMES` → `bs_theme`,
  the seam the icon variants ride).
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-07-31):** the filter's field set — left below as *"a one-line
> client-side match on the title"* — is now **the entry's title and its group's**.
> Still titles, never prose. Measured on the first real page rather than reasoned
> about: with entry titles alone, typing a category name (`loadtest`) matched
> nothing at all, which reads as a broken page rather than as a narrow rule, and
> typing the category is exactly what somebody who knows the toolbox does. `note:`
> stays out, for the reason the decision gives for making entries records at all: a
> note is prose, and a match the reader cannot see in the title it landed on is the
> failure mode records were chosen to avoid. Tokens match with **and**, in any
> order, so a second word narrows. Order is untouched — the filter hides, it never
> sorts.

> **Update (2026-08-01):** the search path gains a rung. **`config/links/icons/` is
> the deployment's own pack, discovered by file name** — dropping `firewall.png` there
> and writing `icon: firewall` is now the whole of it, with no `icons:` entry. The pair
> convention is the built-in pack's own file names (`<name>-on-light.*` /
> `<name>-on-dark.*`); anything else is a single file on the chip; one flat directory,
> no recursion; a non-icon file (a README, a `.DS_Store`) passes in silence. It sits
> **above** the packs a dependent package registers and **below** the `icons:` map,
> which stays the way to say what a file cannot — a remote URL, or `none`. Order
> across roots is unchanged: later root wins, per name, whole.
>
> The reason is a real port. A deployment moving sixty links off an older tool put its
> seven own marks into `config/links/icons/`, wrote `icon: firewall` beside the
> entries, and was told *no icon named 'firewall'* while the file sat in the directory
> the page was reading. Requiring a second declaration for a file already named after
> the thing it draws is a rule with no reader — decision 3's *"a name resolves through
> a search path"* had simply left the deployment's own directory off it. Only the
> **directory** form has one, which is what that form is for
> ([ADR-0031](0031-deployment-config-directory.md) §2): an `icons/` beside a flat
> `config/links.yaml` is a directory in a configuration root, and warns as an
> unrecognized aspect rather than being read as ours.

> **Update (2026-08-02):** decision 9's timer moves off the engine's tick. **A probe
> pass is triggered by somebody opening the page, and only when the newest answer is
> older than `interval:`** — the key keeps its name and its `6h` default, and changes
> meaning from *how often the timer fires* to *how stale an answer may be before an
> open refreshes it*. The pass never blocks the response: the page renders from what is
> already in memory, each verdict carrying its own age, and the answers one open
> triggers appear on the next. One pass at a time, however many readers arrive together.
>
> Two things the trigger has to survive, added after review. An `interval:` this cannot
> read **falls back to the default** instead of raising: the loader keeps the key as raw
> text and does not validate it, so a plausible typo like `6 hours` took the whole page
> to a 500 with nothing warned first; a non-positive one falls back too, since it would
> make every open due. And one target that answers **garbage** costs its own verdict and
> not the sweep — `http.client.HTTPException` is neither an `OSError` nor a `ValueError`
> and came back out of the probe unwrapped, so a typo'd port left every other entry
> unanswered, which the trigger then read as "never asked" and retried on every open.
>
> Decision 9 already named the audience — *the person who maintains the file, and that
> person is looking at this page* — and then put the timer somewhere that runs whether
> or not anybody is. Two things follow that were not visible when this was written.
> **Most deployments would probe an empty set:** decision 8's structural pass already
> rejects a local icon file that is not there and a pack member that is not there, both
> offline and at load, so the only icon a probe can discover anything about is a
> **remote** one — the fill this ADR ranks last and expects to be rare — while links are
> opt-in and default off. And **the tick would have cost a seam for it**: a periodic
> callback on a scheduler built for checks, skipped wherever the engine is disabled,
> which is exactly where the page still works. Triggering from the page needs none of
> that, and probes where the page is read.
>
> The rejected shape is *every n-th open*. A count is unpredictable in both directions:
> five reloads while somebody watches a dashboard would spend five passes, and a page
> opened twice a day would refresh on neither. Time is the honest unit, and it is the
> one already in the file. **Probing at startup stays rejected** for the reason under
> Alternatives; this is that argument one step further — not at boot, not on a clock,
> but when somebody asks.
>
> *Never blocks* is a rule about the **open**, not about the reader. A deliberate **check
> now** control re-probes on demand and, unlike an open, **waits for the answer** under
> an overall deadline — the person who has just fixed a URL is the one case the time gate
> gets wrong, and they are waiting on purpose. It shares the single pass, so a press that
> lands mid-pass joins it; whatever has not answered by the deadline keeps its previous
> verdict and age.

> **Update (2026-08-02, later):** decisions 9–10 gain the rule that makes *one pass at a
> time* survivable. **A pass carries a deadline of its own, and abandons what has not
> answered when it runs out.**
>
> The gap this closes: `REQUEST_TIMEOUT` bounds one **socket operation**, not one
> request. A server that sends a byte every four seconds never times out, and the pass
> waiting on it could not end — the executor was entered as a context manager, and
> leaving one waits for every worker. Because the single pass slot was released only on
> the way out, one such host froze reachability for the life of the process: no open and
> no *check now* could ever start another pass. The page went on showing ages that crept
> upward with nothing behind them.
>
> **It cannot be cancellation.** A request already on the wire cannot be recalled, and a
> thread blocked in `recv` cannot be interrupted. So it is **abandonment**: at the
> deadline the pass keeps what came back, says what did not, stops waiting, and lets the
> next pass have the slot. The three fates are exact, and the middle one is why this is
> worth writing down. **Answered** — the verdict, at the age it arrived. **Never started**
> (still queued, so cancelled) — nothing was asked, so nothing changes and the previous
> verdict and age stand; overwriting it would be this module inventing a failure it never
> observed. **Started and unfinished** — *no answer*, which is a value this ADR already
> has (§10) and deliberately not a death: silence would leave an hours-old *alive* beside
> an entry whose host has been swallowing requests all morning.
>
> The deadline is **derived, not fixed**: `CONCURRENCY` probes run at once, so the honest
> unit is rounds, and sixty entries are ten rounds where six are one. It has a floor
> comfortably above the *check now* deadline, so "the pass carries on without me" stays
> true rather than becoming "the pass expired before you stopped waiting".
>
> Two passes can now be alive at once, so **one has to lose**. Each carries a generation;
> every write, the prune of what the file no longer names, and the release of the pass
> slot check it first. A superseded pass stops writing — two passes interleaving into one
> store would produce a set of answers with no single age, and the freshness line on the
> page is a single age.
>
> What abandonment leaks is **threads and sockets a host is refusing to release**, and
> nothing this side of the wire can make it let go. So there is a cap: past three
> outstanding, no new pass starts. That is a real degradation, and the page **says so**
> rather than looking like a control that does nothing — this is the one condition under
> which the ages beside the entries stop meaning what they say.
>
> One more thing was wrong, and it is recorded here because it made the sentence above it
> false. Verdicts were said to be stored *as they arrive*; they were collected with
> `Executor.map`, which yields in **submission** order. The probes did run concurrently;
> the storing did not, so a slow first target held every later answer out of the store
> until it finished. That is harmless while a pass always completes, and load-bearing the
> moment one may not — "keep what came back" is the whole promise of a deadline.

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
[ADR-0025](0025-check-provided-subnode-metadata.md)), and a subject's runbook belongs
there, next to the thing that fails. So this page is **general helpers** — the shared
Grafana, the ticket queue, the team's toolbox — not per-node documentation. That
removes the temptation to design a link record rich enough to also hang off a status
node.

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

2. **One level of grouping, merged by title, in file order.** Groups with the same
   title across directories **concatenate**, base first, so a site can add entries to a
   shared group. This deliberately differs from the checks loader, which hard-errors on
   overlap ([ADR-0015](0015-check-discovery-union.md)): two checks claiming one node is
   an ambiguity about *truth*, two files contributing to one group is not. Entry order
   is **curated and preserved — never sorted**; an operator who puts *EMERGENCY STOP*
   first means it.

3. **Icons are referenced by name, and the names aggregate.** An entry says
   `icon: grafana`; it never carries a URL. The same application appears many times on a
   real page, so a dozen Grafana links cost **one** icon — one definition, one fetch, one
   probe. A name resolves through a search path, first match wins, in the shape
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
   already carry links, and a check ships its runbook through **its own config** — an
   inline `about`, or a `subnodes:` block layered over a hardcoded per-aspect default via
   `{default}` ([ADR-0013](0013-check-config-on-node.md),
   [ADR-0025](0025-check-provided-subnode-metadata.md)). That already delivers the one
   thing a structured per-node `links:` field would have added — a check shipping its
   runbook once instead of every deployment retyping it — so a second, typed channel for
   the same content is not worth a status-model field, a JSON contract change and an
   `openapi.yaml` bump. The two surfaces stay separate: **this page is general helpers,
   the node knows its own subject.**

6. **An entry may carry one line of Markdown.** `note:` renders inline and muted under
   the title — room for *"page the ISP before touching this"*. No page introduction, no
   group prose: the runbooks live on the checks, and this page is a launcher.

7. **The file is re-read when its mtime changes**, not loaded once at startup. A
   `stat()` per request, a parse only when the file actually changed. Editing links must
   not cost a restart, for the reason given in the context.

8. **Validation splits by cost.** *Structural* checks — schema, unknown icon name,
   duplicate titles within a group, a rejected URL scheme — run **at load**: offline,
   instant, warn-and-continue, in the spirit of the `nodes.yaml` consistency pass
   ([ADR-0012](0012-node-metadata.md)). *Reachability* is a network question and never
   runs at startup: this application must come up while the network is broken.

9. **Reachability is probed on a slow schedule and reported on the page — not on the
   status tree.** The engine's tick supplies the timer; results live in memory and
   render beside the entry that failed. The audience is the person who maintains
   `links.yaml`, and that person is looking at this page; the reader mid-incident finds
   out by clicking.

10. **Probing is opt-in, and the defaults split by how trustworthy the answer is.**
   **Icons are probed by default** — a static asset, no auth, an unambiguous failure.
   **Links are not** — most are behind a corporate login, where `403` may mean "not
   signed in", "your user agent is blocked", or a real wall, and the three are
   indistinguishable from the server. A link opts in per entry, and only
   `404` / `410` / DNS failure / connection refused count as dead; `401` and `403` are
   *alive*. `HEAD` falls back to `GET`, because a `405` is a server's opinion about
   methods, not about existence.

Local icon files make this aspect a **directory**, so the example below is
`config/links/links.yaml` with its files in `config/links/icons/`. A flat
`config/links.yaml` beside a sibling `config/icons/` is *not* the same arrangement and
does not work: `icons` is not an aspect, so it warns as unrecognized and is ignored
([ADR-0031](0031-deployment-config-directory.md) §3). A deployment whose icons are all
built-in or remote URLs needs no directory and can stay flat.

```yaml
# config/links/links.yaml   (icon files live in config/links/icons/)
check:
  icons: true                            # each distinct icon, once
  links: false                           # most are auth-walled; opt in per entry
  interval: 6h
  alive: [200, 301, 302, 401, 403]

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
        check: true
        note: offline-capable, safe for production data
```

## Consequences
- A deployment fills the page with one file in a directory it already points at, and
  gets base-plus-site layering without a second mechanism.
- **The presentation stays in the library**, so the page inherits the themes, the rail,
  the kiosk layout and the band without a deployment having to know they exist. A
  free-Markdown page would have opted out of all of it.
- Entries are **records**, so the filter box is a one-line client-side match on the
  title rather than a search over rendered prose.
- **The status strip is untouched.** `_split_heartbeat` lifts the heartbeat into the
  one-line strip only when it has no children — the guard exists precisely so the strip
  can never hide a subtree ([ADR-0024](0024-dashboard-layout.md)). The reserved
  `/little-sister` line *is* the right home for engine-owned children, and the loader's
  reservation exists to keep it free for them; but the **first** such child costs the
  strip a redesign, and a link checker is too thin a reason to spend that. Deferring
  keeps the option open: if link health should ever roll up into the traffic light, this
  ADR is what gets superseded.
- A dead link is visible where it can be fixed, and never turns the dashboard amber for
  everyone because a Confluence page moved.
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
  referrer-based hotlink protection, URLs that rot on a vendor redesign, every host needing
  a line in a future `img-src` policy, and no icons at all for a deployment without
  outbound access. Hence the preferred order in the decision.
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
  same URL repeats on every entry of an application, and both the fetch and the probe
  multiply with it.
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
- **A `links` check type configured deployment-side.** Avoids the reserved line
  entirely, but links are not infrastructure and have no honest node in a deployment's
  tree — the placement would be arbitrary in every installation.
- **Probing at startup.** Simple and needs no scheduler, but it slows boot, needs the
  network at the worst possible moment, and files its answer in a log nobody reads.
- **Loading once at startup**, consistent with the checks. Rejected for what a restart
  costs while history is in memory.
