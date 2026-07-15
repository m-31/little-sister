# Little Sister — Use Cases (the vision, in scenes)

> Concrete day-to-day scenes of little-sister in use. This is the **vision**, not
> a spec: domain terms are defined in [`project.md`](project.md), the current code
> is in [`architecture.md`](architecture.md).
>
> Names (Robin, Sam…) are illustrative.

---

## 1. The morning glance
Robin starts the day on call. They open little-sister in the browser and land on
`/status`. The whole tree is one calm wall of green, except one branch glowing
amber. Robin clicks that branch to drill in: `payments → gateway` is **WARN**,
and right under it the reason reads *"latency p95 1.8s (threshold 1.0s)."* No
pager, no spelunking through dashboards — thirty seconds and Robin knows where to
look.

## 2. A check trips, and it rolls up
Behind the scenes the engine has been running checks on their own intervals in
the background. The `gateway` HTTP check fires every 15 seconds; on this run it
gets an HTTP 503 and returns **ERROR** with the reason *"503 from /health."*
Because status is a tree, that ERROR rolls **up**: `gateway` → `payments` → the
top-level **Production** node all turn red. Robin's `/status` tab, refreshed,
now shows red at the very top — the single overall status told the whole story
without anyone wiring up a special alert.

The checks themselves are unremarkable and that's the point: one calls an HTTP
health endpoint, another runs a shell command, a third just pings a host. A check
can do whatever it takes to answer "is this thing OK?".

## 3. A planned maintenance window

The team is upgrading the database tonight. Rather than let it page everyone,
Robin marks the `database` subsystem **MAINTENANCE**. On `/status` it turns blue
and stops dragging the parent into the red — the tree shows the system is *down
on purpose*, not broken. When the window closes, the checks take over again and
the node returns to green on its own.

## 4. What changed overnight

Next morning Robin checks the **Events** view: a tidy, reverse-chronological list
of transitions. `cache.redis` went `OK → ERROR` at 02:14 (*"connection
refused"*), then `ERROR → OK` at 02:17 when it recovered. A three-minute blip
nobody had to witness live — but it's on the record, with reasons, if anyone asks
what happened.

## 5. Pulling status into an incident

A real outage hits and Robin opens an incident channel. From the **Text** page
they copy a plain-text snapshot of the tree and paste it straight in:

```
Production: ERROR
  payments: ERROR
    gateway: ERROR - 503 from /health
  database: OK
  cache: WARN - evictions high
```

No screenshots, no reformatting — the status drops cleanly into chat and the
ticket, and everyone's looking at the same picture.

## 6. Runbook links at hand

While firefighting, Robin clicks **Links** — a short, curated set of the runbooks
and dashboards that actually matter for what's on fire. (The team affectionately
calls whoever's on call "the capybara of the day," and this page exists to help
that person move fast.)

## 7. A glance from the menu bar

Robin's teammate Sam rarely keeps a browser tab open. Instead, a small native
**macOS app**, written in **Swift**, sits in the menu bar. It periodically asks a
little-sister instance — running on a different machine — for its status as
**JSON**, and shows a green/amber/red dot. When Sam clicks it, the tree unfolds
natively. little-sister is the **backend**; the Mac app is just one of possibly
many clients reading the same JSON.

```json
{
  "schema_version": 1,
  "generated_at": "2026-06-17T08:14:05Z",
  "status": {
    "path": "Production", "name": "Production",
    "own_code": "UNDEFINED", "code": "ERROR",
    "reasons": [], "timestamp": "2026-06-17T08:14:02Z",
    "children": [
      { "path": "Production.payments", "name": "payments",
        "own_code": "ERROR", "code": "ERROR",
        "reasons": ["503 from /health"], "timestamp": "2026-06-17T08:14:02Z",
        "children": [] }
    ]
  }
}
```

## 8. One screen across many sites

The company runs systems in three places: the office, a colo, and a cloud region.
Each site runs its **own** little-sister as a **satellite**, watching the machines
it lives next to. The central instance runs a handful of **satellite checks** —
each one fetches a satellite's JSON and **grafts that whole branch** into the
central tree at a path like `sites.colo`. The result: one `/status` screen for
the entire company, assembled from instances that each only know their own
corner. Because every instance speaks the same JSON, the output of one is simply
the input of the next.

## 9. Why it lives on a Mac
little-sister itself runs on **macOS**. From there a check can reach into the
**Apple ecosystem**, ping the **Linux** boxes on the local network, and call out
to **remote servers** — the same uniform `Status` regardless of what was actually
checked or where it lives.

## 10. The wall everyone glances at

A spare monitor hangs in the team room, driven by a Raspberry Pi in kiosk mode
showing little-sister's status grid in big, read-at-a-distance type — a monitor
glyph by the title, a rotating quip in the corner. Nobody touches it; it just sits
there, green, at the edge of everyone's vision. When a tile goes red, the room
notices before anyone opens a laptop. By the door, an even simpler screen runs the
**traffic light**: the whole display is a single color — green, amber, or red —
for the root's rolled-up status, with the failing services listed when it's not
green. You can read the health of everything on your way out the door.

