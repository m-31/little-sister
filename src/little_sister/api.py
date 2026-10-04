"""Serialization and auth helpers for the JSON output (backend mode).

Pure, framework-agnostic functions shared by the web layer and — later — the
satellite parser (ADR-0080). The Flask glue (content negotiation, building the
HTTP responses) stays in :mod:`little_sister.app`.

**The envelope is the snapshot, published** (ADR-0080). Everything the dashboard
renders it renders from :class:`~little_sister.tree.StatusSnapshot`, and this module
is that snapshot in JSON — no projection, no second vocabulary. The rule that keeps it
so: a field added to the snapshot is added here in the same change, which is
compatible (``schema_version`` stays 2, the spec's minor moves) and therefore cheap
for whoever adds it. The rule's other edge is enforced here too, by simply not writing
the code: nothing is emitted that the snapshot cannot produce, because a field the
schema promises and no run ever fills is a promise no test can check.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from little_sister import instants
from little_sister.maintenance import MaintenanceEntry
from little_sister.secrets import same_secret
from little_sister.tree import ReasonLine, StatusSnapshot

#: Major version of the JSON / federation schema (ADR-0080). Bumped only when a field
#: changes meaning or goes; an added field keeps it and moves the spec's minor.
SCHEMA_VERSION = 2


def _maintenance(entry: MaintenanceEntry | None) -> dict[str, str] | None:
    """A maintenance pin — why, by whom, when, until when — or ``None`` where nothing
    is pinned (ADR-0014).

    One nullable object, in place of the bool and the details object that used to sit
    beside each other: *pinned* is this being non-null, and two fields that must agree
    eventually will not. Both dates ship, because both are kept: ``set_*`` is the last
    write, ``created_*`` the first, and an entry whose creation was never recorded
    reads its set (:class:`~little_sister.maintenance.MaintenanceEntry`), so the pair
    is always present and never guessed at here.
    """
    if entry is None:
        return None
    # **`note`, not `reason`.** The model's field is `reason` and ADR-0047 renames it
    # to `note` when the note history is built — so the envelope would break a second
    # time over one word. This is the release in which changing it is free, so it is
    # changed here: the value is what it always was, and the name is the one that will
    # be true. The two disagree until that record lands, which is why this comment is
    # here rather than in a reader's way.
    return {
        "note": entry.reason,
        "set_by": entry.set_by,
        "set_at": instants.stamp(entry.set_at),
        "expires_at": instants.stamp(entry.expires_at),
        "created_by": entry.created_by,
        "created_at": instants.stamp(entry.created_at),
    }


def _entry(line: ReasonLine) -> dict[str, Any]:
    """One of a node's entries: its key, its text, whatever code and pin it carries.

    ``code`` is ``None`` where the entry carries the node's rather than one of its
    own (ADR-0042) — the distinction a client needs to know whether it may color the
    line by itself.

    ``subject`` and ``data`` are the two fields ADR-0080 said would join the entry
    "in the change that adds them to the snapshot", and this is that change:
    compatible, ``schema_version`` unchanged, the spec's minor moved, invisible to a
    client that does not want them. ``subject`` is what the line is about, empty
    where the check did not say; ``data`` is the record it read, or null. The record
    is plain JSON the client renders as it likes — a handful of names carry a time
    in RFC 3339 UTC, the rest is the check's own vocabulary.

    ``refused`` is 2.6.0's (ADR-0093): where the seam refused the line's record,
    ``data`` is null and this is why, in the sentence the node's page shows; null on
    every other line, and always present, for the reason the two before it are.
    """
    return {
        "slug": line.slug,
        "text": line.text,
        "code": None if line.code is None else line.code.name,
        "running": line.running,
        "subject": line.subject,
        "data": line.data,
        "refused": line.refused or None,
        "maintenance": _maintenance(line.maintenance),
    }


def _entries(snapshot: StatusSnapshot) -> dict[str, Any]:
    """A node's entries, as an object rather than an array of strings.

    ``addressable`` is the snapshot's ``members``: whether these items may be pinned
    one by one (ADR-0036). Prose and members are different things, and the array of
    bare strings could say which only by convention. Order is the check's own and is
    never sorted.
    """
    return {
        "addressable": snapshot.members,
        "items": [_entry(line) for line in snapshot.reasons],
    }


def _run(snapshot: StatusSnapshot) -> dict[str, Any] | None:
    """The run facts for the node, or ``None`` where the block is **absent**.

    Absent means *nothing answers for this node* — a container above two or more
    checks, or a node below a branch check's mount whose next update belongs one level
    up (ADR-0044). That is a different fact from *a check answers and has never
    written*, which is the block present with a null ``observed_at``, and the two were
    the same null before this version (ADR-0027's defect).

    Inside it, a null is a fact of its own: ``wall_seconds`` is null for a
    secret-pinned check, which never runs, and ``next_at`` for a one-shot, which has
    no live schedule. ``next_at`` is the engine's armed slot and never
    ``observed_at + frequency`` — a failing check's slot is pulled in (ADR-0033), so
    the arithmetic answer is wrong exactly when somebody is watching a failure.
    """
    facts = snapshot.run
    if snapshot.timestamp is None and facts is None:
        return None
    stamp = snapshot.timestamp
    run: dict[str, Any] = {
        "observed_at": None if stamp is None else instants.stamp(stamp),
        "wall_seconds": None if facts is None else facts.wall_seconds,
        "next_at": (None if facts is None or facts.next_run_at is None
                    else instants.stamp(facts.next_run_at)),
    }
    if snapshot.frequency_seconds is not None:
        run["frequency_seconds"] = snapshot.frequency_seconds
    if snapshot.stale_after_seconds is not None:
        run["stale_after_seconds"] = snapshot.stale_after_seconds
    return run


def _contribution(snapshot: StatusSnapshot) -> dict[str, Any] | None:
    """What this node's parent counted, and the rule that made it so — or ``None``
    where the parent counted the node's ``code``, which is the ordinary case.

    ADR-0032 rule 5 reaching the API: a transformed contribution is visible and
    attributable, so a client can explain a red root by walking down it rather than
    guessing. Null on the ordinary case keeps the interesting one easy to find and
    keeps a healthy tree's response the size it was.

    The value is the snapshot's, not derived here: a rule that **withholds** a node
    could be read back off its code, but one that **delays** a contribution — the
    damping counter — cannot, because the node's own code is precisely the value the
    parent did *not* count. `code` is null for the first kind and a real code for
    the second, which is the distinction ADR-0080 decision 2 described before there
    was a rule of the second kind.
    """
    if snapshot.contribution is None:
        return None
    code = snapshot.contribution.code
    return {"code": None if code is None else code.name,
            "by": snapshot.contribution.by}


def snapshot_to_dict(snapshot: StatusSnapshot) -> dict[str, Any]:
    """Serialize a status snapshot subtree to the ADR-0080 JSON shape.

    The three statuses are ADR-0032's, under their own names: ``reported`` is what the
    check said, ``own`` the first derived value — a pin, or a member set every one of
    whose entries is pinned — and ``code`` the effective, rolled-up, stale-degraded
    one. A display client reads ``code``; a federating parent grafts ``own`` plus
    ``children`` and re-rolls locally rather than aggregating twice.

    ``description``, ``about``, ``title``, ``config`` and ``report`` are raw Markdown
    the client renders (ADR-0018); ``config`` and ``report`` are the owning check's own
    text and are empty on a node two checks share (ADR-0044 decision 1). ``stale`` is
    the server's verdict and never something a client recomputes from a clock it does
    not share (ADR-0005).
    """
    return {
        "path": snapshot.path,
        "name": snapshot.name,
        "reported": snapshot.reported_code.name,
        "own": snapshot.own_code.name,
        "code": snapshot.code.name,
        "contribution": _contribution(snapshot),
        "description": snapshot.description,
        "about": snapshot.about,
        "title": snapshot.title,
        "config": snapshot.config,
        "report": snapshot.report,
        "order": snapshot.order,
        "show_when_quiet": snapshot.show_when_quiet,
        "maintenance": _maintenance(snapshot.maintenance_entry),
        "stale": snapshot.stale,
        # **What this node's check measured, and the object it measured**
        # (ADR-0085). The object's own identifier rather than the node's path,
        # because the path is the deployment's label; both empty and null on a node
        # no check measures, and on a mount two checks share, where the last writer
        # cannot be believed. A client reads `record` as data about the reading, not
        # as a claim: what alarms is a reason.
        "subject": snapshot.subject,
        "record": snapshot.record,
        # *Which* dependency, not just that there was one: `contribution.by` names
        # the rule, and the one thing an operator needs from a shielded node is
        # where to go and look. Carried even where another rule spoke first — a
        # pinned node behind a failed gateway is shielded whether or not the pin
        # is what named it — and null on the ordinary node (ADR-0080 decision 1).
        "shielded_by": snapshot.shielded_by,
        "changes": snapshot.changes,
        **({} if (run := _run(snapshot)) is None else {"run": run}),
        "entries": _entries(snapshot),
        "children": [snapshot_to_dict(child) for child in snapshot.children],
    }


def status_envelope(snapshot: StatusSnapshot, *, version: str = "",
                    engine: str = "", now: datetime | None = None) -> dict[str, Any]:
    """Wrap a serialized snapshot in the versioned response envelope.

    ``generated_at`` is the serving instance's clock (UTC) at snapshot time, and
    ``instance`` says who answered — the version and the engine's state, the two facts
    ``/health`` withholds from an ungated caller (ADR-0066) and which are fine behind
    the bearer token. Per envelope and never per node: one response is one instance's
    answer.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": instants.stamp(now or instants.now()),
        "instance": {"version": version, "engine": engine},
        "status": snapshot_to_dict(snapshot),
    }


def problem(status: int, title: str, detail: str | None = None) -> dict[str, Any]:
    """Build an RFC 9457 problem object (ADR-0080 / Zalando #176)."""
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    return body


def parse_api_tokens(raw: str) -> dict[str, str]:
    """Parse ``LITTLE_SISTER_API_TOKENS`` (``name=token,name2=token2``) into a
    mapping of client name to token. Empty or malformed entries are skipped.
    """
    tokens: dict[str, str] = {}
    for entry in raw.split(","):
        name, _, token = entry.partition("=")
        name, token = name.strip(), token.strip()
        if name and token:
            tokens[name] = token
    return tokens


def authenticate(auth_header: str | None,
                 tokens: Mapping[str, str]) -> str | None:
    """Return the client name for a valid ``Authorization: Bearer`` token, else
    ``None``. Tokens are compared in constant time (ADR-0008), through
    :func:`little_sister.secrets.same_secret` — a bearer token arrives off the wire
    and may be any bytes at all, which the standard library's own comparison refuses
    to be handed as text.
    """
    if not auth_header:
        return None
    scheme, _, value = auth_header.partition(" ")
    presented = value.strip()
    if scheme.lower() != "bearer" or not presented:
        return None
    for name, token in tokens.items():
        if same_secret(presented, token):
            return name
    return None
