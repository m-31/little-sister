# ADR-0005 — Dashboard freshness & engine self-monitoring

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-06-20)
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (the engine),
  [ADR-0039](0039-status-rollup-semantics.md) (roll-up),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (the editor the poll
  waits for), [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (decision 5: the
  freshness backstop holds under a pin),
  [ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  (decision 2: a branch's period, which a node gone stale moves).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
State lives in memory and the dashboard is server-rendered, so two things can go
silently stale: the **page** (loaded minutes ago) and the **data** (a check that
stopped running, or the engine itself dying). A confidently-green tile for a check
that died is the dangerous case — green must mean *freshly verified*.

## Decision

**1. Stale statuses degrade.** A node that reports on a schedule but hasn't been
observed within roughly two of its intervals (`frequency + max(frequency, 30s)`)
is **stale**. Its status is degraded to at least `WARN` by *worse-of* — so a real
`ERROR` is never softened — and that rolls up the tree. A node that never reported
(`UNDEFINED`) is exempt, and so is one whose check reports `MAINTENANCE` itself: neither
carries a severity to degrade. A pin exempts nothing — a pinned check that stops running
escalates as any other does
([ADR-0041](0041-maintenance-is-a-contribution-rule.md) decision 5). Staleness is
computed at **render time** in the snapshot (it depends on the clock, not on a check
running); it is **not** recorded as an event.

The interval is the check's **period**, so the rule reaches exactly as far as
`frequency` does. A paced check has no period of its own
([ADR-0078](0078-the-unit-is-what-the-engine-releases.md)) and is held to a declared
cycle ceiling instead; both are one rule seen twice, and
[ADR-0079](0079-freshness-is-a-stated-tolerance.md) states it: freshness is judged
against a tolerance the deployment **stated**. Stated rather than derived, because a
derived tolerance would grow with the estate — green would stop meaning *freshly
verified* at exactly the moment the estate outgrew what it can read.

**2. The dashboard polls.** The page re-fetches a server-rendered fragment
(`/status?fragment=1`, the same template) every ~10s and swaps it in, showing
"updated HH:MM:SS". If a refresh fails it flags "could not refresh — last ok …"
rather than silently showing old content — the page never lies about being live.
A blip and an outage are not treated alike. The "updated …" stamp is
**server-seeded** into the page (`data-rendered-at`), so a dashboard that never
reaches the server again still dates its data; the poll is the shared
`static/js/poll.js` (the `/system` page uses it too); a fragment response without
`X-Rendered-At` — the login redirect after session expiry — counts as a failed
poll, never as content. A **sustained** outage escalates: after six consecutive
misses (~1 min) the line shows a legible age (*"could not refresh for 14 min — last
ok …"*), a banner rises above the content, the frozen content dims and the tab
title gains a "(stale) " prefix — all reset by the first good poll, with an
immediate re-poll on `visibilitychange` so a woken tab self-heals at once. Session
expiry banners "reload to log in" instead of a misleading age.

The poll waits for an open editor
([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) decision 7). On the
dashboard and on a branch's page an editor of a pin opens inside what the poll
swaps, so while one is open nothing is fetched and nothing is swapped. The line
says so at once — *updated … — paused while editing* — and after a minute the page
dims, all of it but the card or the head being edited, as it does under a
sustained outage. When the editor closes the line drops the words and the next
poll brings the page up to date; a page that had dimmed is polled at once. The
promise stands: a page that is not live says so.

**3. The engine monitors itself.** The engine heartbeats a top-level
`little-sister` node every scheduler tick; if the scheduler stalls, that node goes
stale (red) via (1) — the monitor monitors itself, with no separate watchdog
subsystem. The scheduler loop is hardened so a transient error logs and continues
instead of killing the thread. Whole-process death is the job of an external
supervisor (launchd / systemd / gunicorn restart).

The heartbeat node renders as the dashboard's slim **status strip** rather than a
grid tile, paired with the "updated …" line and polled with the fragment — under a
sustained-outage banner it dims with the frozen content, while a *stale heartbeat
itself* stays vivid (the self-monitor's alarm). Its path is **reserved**: the loader
rejects custom checks on the `/little-sister` line, so nothing user-configured can
hide behind the one-line strip ([ADR-0056](0056-stable-useful-dashboard-flow.md) decision 3).

The heartbeat node also carries the engine's **configuration** verdict. A
deployment whose config tree is absent no longer starts at all
([ADR-0031](0031-deployment-config-directory.md)); but a tree that is present and
simply holds **no checks** is a legitimate state — a fresh install, a deployment
mid-bring-up — so the engine runs, a warning names the reason and the directories
searched, and the heartbeat reports **WARN** with that reason. This matters because
with zero checks the tree is *only* the heartbeat: an OK heartbeat would roll up to
an all-green root while nothing whatsoever is being watched, which is precisely the
lie decision (1) exists to prevent. Amber, saying "no checks configured", is the
honest reading.

## Consequences
- Green means "freshly verified"; a dead check or a dead engine surfaces
  automatically (per-check staleness + the heartbeat node).
- Staleness is a *view* concern: `StatusTree.snapshot` degrades and flags it, and
  `Status.get_status_code` / `effective` stay raw.
- No *went stale* row is written to the event log. A branch's period, kept beside the
  log, says when a node beneath it went stale, dated by the reading's last observation
  and its tolerance
  ([ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  decision 2).
- The heartbeat adds ~1 cheap upsert per second.

## Alternatives considered
- **Mark stale but keep the code** — less safe; a stale `OK` would still read green.
- **Full-page meta-refresh** — trivial but flickers and resets scroll.
- **Server-sent events / push** — real-time but more moving parts (a connection per
  viewer); better once there's a JSON API / persistence.
- **A dedicated watchdog thread** that restarts the scheduler — more machinery than
  loop-hardening + the heartbeat node warrant; easy to add later if needed.
