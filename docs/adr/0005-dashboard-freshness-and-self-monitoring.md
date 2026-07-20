# ADR-0005 — Dashboard freshness & engine self-monitoring

- **Status:** Accepted
- **Date:** 2026-06-19
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (the engine),
  [ADR-0004](0004-status-aggregation-semantics.md) (roll-up).
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-07-20):** decision §2 no longer treats a blip and an outage
> alike. The "updated …" stamp is **server-seeded** into the page
> (`data-rendered-at`), so a dashboard that never reaches the server again
> still dates its data; the poll is the shared `static/js/poll.js` (the
> `/system` page uses it too); a fragment response without `X-Rendered-At` —
> the login redirect after session expiry — counts as a failed poll, never as
> content. A **sustained** outage escalates: after six consecutive misses
> (~1 min) the line shows a legible age (*"could not refresh for 14 min — last
> ok …"*), a banner rises above the content, the frozen content dims and the
> tab title gains a "(stale) " prefix — all reset by the first good poll, with
> an immediate re-poll on `visibilitychange` so a woken tab self-heals at
> once. Session expiry banners "reload to log in" instead of a misleading age.
>
> **Update (2026-07-20):** the heartbeat node renders as the
> dashboard's slim **status strip** (no longer a grid tile), paired with the
> "updated …" line and polled with the fragment — under a sustained-outage
> banner it dims with the frozen content, while a *stale heartbeat itself*
> stays vivid (the self-monitor's alarm). Its path is **reserved**: the loader
> rejects custom checks on the `/little-sister` line, so nothing
> user-configured can hide behind the one-line strip ([ADR-0024](0024-dashboard-layout.md)).

## Context
State lives in memory and the dashboard is server-rendered, so two things can go
silently stale: the **page** (loaded minutes ago) and the **data** (a check that
stopped running, or the engine itself dying). A confidently-green tile for a check
that died is the dangerous case — green must mean *freshly verified*.

## Decision

**1. Stale statuses degrade.** A node that reports on a schedule but hasn't been
observed within roughly two of its intervals (`frequency + max(frequency, 30s)`)
is **stale**. Its status is degraded to at least `WARN` by *worse-of* — so a real
`ERROR` is never softened — and that rolls up the tree. Maintenance nodes and
never-reported (`UNDEFINED`) nodes are exempt. Staleness is computed at **render
time** in the snapshot (it depends on the clock, not on a check running); it is
**not** recorded as an event.

**2. The dashboard polls.** The page re-fetches a server-rendered fragment
(`/status?fragment=1`, the same template) every ~10s and swaps it in, showing
"updated HH:MM:SS". If a refresh fails it flags "could not refresh — last ok …"
rather than silently showing old content — the page never lies about being live.

**3. The engine monitors itself.** The engine heartbeats a top-level
`little-sister` node every scheduler tick; if the scheduler stalls, that node goes
stale (red) via (1) — the monitor monitors itself, with no separate watchdog
subsystem. The scheduler loop is hardened so a transient error logs and continues
instead of killing the thread. Whole-process death is the job of an external
supervisor (launchd / systemd / gunicorn restart).

## Consequences
- Green means "freshly verified"; a dead check or a dead engine surfaces
  automatically (per-check staleness + the heartbeat node).
- Staleness is a *view* concern: `StatusTree.snapshot` degrades and flags it;
  `Status.get_status_code` / `effective` stay raw, and the event log / history keep
  recording only real check transitions.
- No "went stale" event is recorded (that would need a periodic sweep) — deferred.
- The heartbeat adds ~1 cheap upsert per second.

## Alternatives considered
- **Mark stale but keep the code** — less safe; a stale `OK` would still read green.
- **Full-page meta-refresh** — trivial but flickers and resets scroll.
- **Server-sent events / push** — real-time but more moving parts (a connection per
  viewer); better once there's a JSON API / persistence.
- **A dedicated watchdog thread** that restarts the scheduler — more machinery than
  loop-hardening + the heartbeat node warrant; easy to add later if needed.
