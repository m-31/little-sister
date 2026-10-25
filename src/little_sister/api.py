"""Serialization and auth helpers for the JSON output (backend mode).

Pure, framework-agnostic functions shared by the web layer and — later — the
satellite parser (ADR-0080). The Flask glue (content negotiation, building the
HTTP responses) stays in :mod:`little_sister.app`.

Two reads: the status tree (:func:`status_envelope`) and the series that stand at or
beneath a node (:func:`series_envelope`, ADR-0122).

**The envelope is the snapshot, published** (ADR-0080). Everything the dashboard
renders it renders from :class:`~little_sister.tree.StatusSnapshot`, and this module
is that snapshot in JSON — no projection, no second vocabulary. The rule that keeps it
so: a field added to the snapshot is added here in the same change, which is
compatible (``schema_version`` stays, the spec's minor moves) and therefore cheap
for whoever adds it. The rule's other edge is enforced here too, by simply not writing
the code: nothing is emitted that the snapshot cannot produce, because a field the
schema promises and no run ever fills is a promise no test can check.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from little_sister import instants
from little_sister.aggregation import AggregationRule
from little_sister.codes import StatusCode
from little_sister.measures import Measure
from little_sister.pins import MAINTENANCE, Pin
from little_sister.secrets import same_secret
from little_sister.series import Placed
from little_sister.tree import (
    ACCEPTED,
    AGGREGATION_RULE,
    MAINTENANCE_RULE,
    SEEN_RULE,
    Period,
    ReasonLine,
    RuleAt,
    StatusSnapshot,
    lines_rules,
)

#: Major version of the JSON / federation schema (ADR-0080). Bumped only when a field
#: changes meaning or goes; an added field keeps it and moves the spec's minor. 3 since
#: every rule on a part became one list, ``handled``, and ``maintenance`` went
#: (ADR-0141 decision 3).
SCHEMA_VERSION = 3

#: Where a rule in ``handled`` comes from: a person set it, or the deployment's
#: configuration declares it.
PERSON = "person"
CONFIGURATION = "configuration"


def _pin(pin: Pin) -> dict[str, Any]:
    """A pin as ``handled`` lists it (ADR-0141 decision 3): its id and its kind, that
    a person set it, its note, who set it last and when and who first did, when it
    ends — null where it has no end, a *seen* given none — and what it makes its part
    count as, in the notation a configured rule's table is written in: a maintenance
    pin's part counting ``nothing``, a seen one's failure counting ``OK``. Both dates
    ship, because both are kept: ``set_*`` is the last write, ``created_*`` the first,
    and a pin whose creation was never recorded reads its set, so the pair is always
    present and never guessed at here.

    **An acknowledgment adds what it is bound to** (ADR-0142): the ``status`` it was
    set at, which a worse one ends, and the ``occurrence`` of the failure it accepted
    — the line's, its type's field or its reading's identity — null where it is bound
    to the failing stretch it was set in."""
    said: dict[str, Any] = {
        "id": pin.id,
        "kind": pin.kind,
        "source": PERSON,
        "note": pin.note,
        "set_by": pin.set_by,
        "set_at": instants.stamp(pin.set_at),
        "created_by": pin.created_by,
        "created_at": instants.stamp(pin.created_at),
        "expires_at": (None if pin.expires_at is None
                       else instants.stamp(pin.expires_at)),
        "counts_as": ("nothing" if pin.kind == MAINTENANCE
                      else {key.name: value.name for key, value in ACCEPTED.entries}),
    }
    if pin.acknowledgment:
        said["status"] = None if pin.status is None else pin.status.name
        said["occurrence"] = pin.occurrence or None
    return said


def _configured(at: RuleAt) -> dict[str, Any]:
    """A configured rule as ``handled`` lists it where it acts (ADR-0137, ADR-0141
    decision 3): its name for its id, that the configuration declares it, its note,
    the file it is written in and the day it says it stands from, where it acts —
    ``node``, ``lines`` or ``children`` — and its table as the file writes it; with
    the lines or the children it names, where it names some, and with a count, how
    many of the parts it counts fail."""
    rule = at.rule
    said: dict[str, Any] = {
        "id": rule.name,
        "kind": AGGREGATION_RULE,
        "source": CONFIGURATION,
        "note": rule.note,
        "file": str(rule.file),
        "since": rule.since.isoformat(),
        "level": rule.level,
        "counts_as": _table(rule),
    }
    named = rule.lines if rule.level == "lines" else rule.children
    if named is not None:
        said[rule.level] = list(named)
    if rule.count is not None:
        said["while_fewer_than"] = rule.count
        said["failing"] = at.failing
    return said


def _table(rule: AggregationRule) -> dict[str, str] | str:
    """A configured rule's table in the notation ``config/aggregation.yaml`` writes
    it in: ``nothing``, or each status it names with what that counts as."""
    table = rule.table
    if table.left_out:
        return "nothing"
    return {key.name: value.name for key, value in table.entries}


def _acting(at: RuleAt | None) -> bool:
    """Whether a configured rule changes what its part counts as now — the one
    predicate its block on the wall follows (ADR-0135 decision 9)."""
    return at is not None and at.changes


def _handled(snapshot: StatusSnapshot) -> list[dict[str, Any]]:
    """What handles a node now (ADR-0141 decision 3): a person's pin while it stands,
    and a configured rule while it changes what counts — on what the node passes up,
    on how its parent counts it among its children, on how its children count, on
    how its lines count. Empty on most nodes."""
    handled: list[dict[str, Any]] = []
    if snapshot.maintenance_entry is not None:
        handled.append(_pin(snapshot.maintenance_entry))
    if snapshot.acknowledgment is not None:
        handled.append(_pin(snapshot.acknowledgment))
    for at in (snapshot.rule, snapshot.parent_rule, snapshot.children_rule):
        if _acting(at):
            assert at is not None
            handled.append(_configured(at))
    handled.extend(_configured(at) for at in lines_rules(snapshot) if at.changes)
    return handled


def _line_handled(line: ReasonLine) -> list[dict[str, Any]]:
    """What handles one of a node's lines now: its pin, its acknowledgment, and a
    configured rule on the node's lines while it changes how the line counts."""
    handled: list[dict[str, Any]] = []
    if line.maintenance is not None:
        handled.append(_pin(line.maintenance))
    if line.acknowledgment is not None:
        handled.append(_pin(line.acknowledgment))
    if _acting(line.rule):
        assert line.rule is not None
        handled.append(_configured(line.rule))
    return handled


def _entry(line: ReasonLine, node: StatusSnapshot) -> dict[str, Any]:
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

    ``form`` is 2.8.0's (ADR-0126 decision 7): the form the line was written from,
    where its check's grading asked the library for it — the key a deployment's
    ``display:`` block re-words that line under — and null on a line its check wrote
    as a sentence of its own; always present, as ``refused`` is.

    ``grading`` is 2.8.0's too (ADR-0131 decision 1): the grading that decided the
    line's code, where one did — the name a deployment writes the keys of to grade
    that line differently — and null on every other line; always present, as
    ``form`` is.

    ``contribution`` is 2.11.0's (ADR-0137): what the line's node counted of it, and
    the rule that made that something else, as a node's says what its parent
    counted — so the virtual children read as the real ones do (ADR-0032 decision
    8). A configured rule on the node's lines that changes it, ``aggregation``, its
    code what the line counts as or null where it counts nothing; a pin, which is
    ``maintenance`` and counts nothing; and null where the node counts the line as
    it reads. Always present, as ``grading`` is. Since 3.0.0 it names the rule that
    decided, ``rule``, which ``handled`` lists (ADR-0141 decision 3).

    ``handled`` is 3.0.0's, where the pin's own object stood: what handles the line
    now, a list as a node's is. A *seen* on the line is among them, and makes its
    ``contribution`` ``OK`` by ``seen`` while it reads a failure (ADR-0142).
    """
    return {
        "slug": line.slug,
        "text": line.text,
        "code": None if line.code is None else line.code.name,
        "running": line.running,
        "subject": line.subject,
        "data": line.data,
        "refused": line.refused or None,
        "form": line.form or None,
        "grading": line.grading or None,
        "handled": _line_handled(line),
        "contribution": _line_contribution(line, node),
    }


def _line_contribution(line: ReasonLine,
                       node: StatusSnapshot) -> dict[str, Any] | None:
    """What a line's node counted of it, and why, where that is not the line as it
    reads (ADR-0137): a pin counts nothing of it, a person's acknowledgment counts
    its failure as OK (ADR-0142), and a configured rule what its table makes of
    it."""
    if line.maintenance is not None:
        return {"code": None, "by": MAINTENANCE_RULE, "rule": line.maintenance.id}
    if line.acknowledgment is not None:
        reads = line.code if line.code is not None else node.reported_code
        if reads in (StatusCode.WARN, StatusCode.ERROR):
            return {"code": StatusCode.OK.name, "by": SEEN_RULE,
                    "rule": line.acknowledgment.id}
        return None
    if line.rule is None or not line.rule.changes:
        return None
    counts = line.rule.counts
    return {"code": None if counts is None else counts.name, "by": AGGREGATION_RULE,
            "rule": line.rule.rule.name}


def _entries(snapshot: StatusSnapshot) -> dict[str, Any]:
    """A node's entries, as an object rather than an array of strings.

    ``addressable`` is the snapshot's ``members``: whether these items may be pinned
    one by one (ADR-0036). Prose and members are different things, and the array of
    bare strings could say which only by convention. Order is the check's own and is
    never sorted.
    """
    return {
        "addressable": snapshot.members,
        "items": [_entry(line, snapshot) for line in snapshot.reasons],
    }


def _period(period: Period) -> dict[str, Any]:
    """The period of what a node shows, in the kept entry's words (ADR-0132 decision
    7): ``since``, and either ``before``, a bound, or ``was`` and ``cause`` where they
    are said, then the ``by`` of the node whose change began it, and the ``rule`` the
    deployment configures where a rule's beginning did (ADR-0137 decision 11). Its
    code is the ``code`` beside it, so it carries none of its own."""
    return {**period.began.to_dict(), **({"by": period.by} if period.by else {}),
            **({"rule": period.rule} if period.rule else {})}


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
            "by": snapshot.contribution.by,
            "rule": snapshot.contribution.rule or None}


#: The absolute address of a node's handbook by its path, as the request that asked
#: reached the instance (ADR-0133 decision 3): the web layer's to say, which holds the
#: request and the routes.
Handbooks = Callable[[str], str]


def snapshot_to_dict(snapshot: StatusSnapshot, *,
                     handbooks: Handbooks | None = None) -> dict[str, Any]:
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

    **Each code's period stands beside it** (ADR-0132 decision 7): ``own_period``,
    when the node's own status began, absent on a node that declares nothing; and
    ``period``, since when it has shown ``code`` and the node whose change began it,
    absent on a leaf, whose one period is ``own_period``, and wherever it is not of the
    ``code`` beside it — which the snapshot has decided, so no client compares the two.

    **A node that has a handbook says where it is** (ADR-0133 decision 3):
    ``handbook``, the absolute address of its Handbook view, which ``handbooks`` says
    from the request that asked — absent on a node that has none, and wherever no
    request asked, as for a fixture. The handbook's text rides in no envelope, and a
    link a text writes in the short form, ``handbook#sign-in``, stays as written: it
    means this address and that section (decision 4).

    **A node's own details**, as the snapshot holds them (ADR-0133 decision 6):
    ``details``, each key with its Markdown, raw, and who gave it — ``type`` or
    ``deployment`` — in their order, the type's first, a key both name once for each;
    absent on a node that has none. What the deployment gives holds for every node
    beneath, key by key, the nearest winning, which a client resolves from the nodes
    above, as the contract says; the type's are their node's alone. So the envelope
    carries each detail once, where it is given, and never a card's resolved rows.

    **Every tag the node carries** (ADR-0139 decision 6): ``tags``, those written for
    it and for every node above it, in the order its card lists them; absent on a node
    that carries none. Unlike the details they are the node's whole set, so that a
    client asks whether a node carries a tag of the node in hand, in a subtree fetched
    by its path too, whose root's nodes above are not in the response.
    """
    return {
        "path": snapshot.path,
        "name": snapshot.name,
        "reported": snapshot.reported_code.name,
        "own": snapshot.own_code.name,
        **({} if snapshot.own_period is None
           else {"own_period": snapshot.own_period.to_dict()}),
        "code": snapshot.code.name,
        **({} if snapshot.period is None else {"period": _period(snapshot.period)}),
        "contribution": _contribution(snapshot),
        "description": snapshot.description,
        "about": snapshot.about,
        **({"handbook": handbooks(snapshot.path)}
           if handbooks is not None and snapshot.has_handbook else {}),
        **({"details": [{"key": detail.key, "text": detail.text, "by": detail.by}
                        for detail in snapshot.details]}
           if snapshot.details else {}),
        **({"tags": list(snapshot.tags)} if snapshot.tags else {}),
        "title": snapshot.title,
        "config": snapshot.config,
        "report": snapshot.report,
        "order": snapshot.order,
        "show_when_quiet": snapshot.show_when_quiet,
        "handled": _handled(snapshot),
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
        "children": [snapshot_to_dict(child, handbooks=handbooks)
                     for child in snapshot.children],
    }


def status_envelope(snapshot: StatusSnapshot, *, version: str = "",
                    engine: str = "", now: datetime | None = None,
                    handbooks: Handbooks | None = None) -> dict[str, Any]:
    """Wrap a serialized snapshot in the versioned response envelope — each node's
    handbook addressed by ``handbooks``, where one is (:func:`snapshot_to_dict`).

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
        "status": snapshot_to_dict(snapshot, handbooks=handbooks),
    }


@dataclass(frozen=True)
class StandingSeries:
    """A series where the series read answers it (ADR-0122 decision 3): the ``node``
    it is shown on, by its path; the key it is kept under — its check's
    ``type_name`` and ``mount``, and its ``subject``; the measures that stand at or
    beneath the node asked, each with the path of the node its curve stands on; and
    its readings in the window, oldest first.

    What stands where is the web layer's to say — it holds the tree and the engine,
    and the Series view asks the same question — so this is what it hands over, and
    everything below is spelling.
    """

    node: str
    type_name: str
    mount: str
    subject: str
    measures: tuple[tuple[Measure, str], ...]
    readings: tuple[Placed, ...]


def _reading(placed: Placed) -> dict[str, Any]:
    """One kept reading, as ADR-0106 decision 6 lists it and ADR-0122 decision 5
    names it.

    ``at`` is the time on the series' clock — the record's own where it has one, and
    otherwise when it was first observed — and ``observed_at`` when the engine last
    took it: two clocks, both kept (ADR-0087 decision 6). ``code`` and ``texts`` are
    what stood where the reading landed (decision 8): null and empty where it stood
    nowhere, and an absence is never an ``OK``. ``identity`` and ``state`` are text,
    at most one of them set, both empty for a reading that is always a new one.
    ``record`` is the record whole — the word a node's measurement has in the status
    read — copied, so that nothing here hands out what the store holds.
    """
    record = placed.record
    return {
        "at": instants.stamp(placed.at),
        "observed_at": instants.stamp(record.observed_at),
        "code": None if record.code is None else record.code.name,
        "texts": list(record.texts),
        "identity": record.identity,
        "state": record.state,
        "record": dict(record.data),
    }


def _measure(measure: Measure, node: str) -> dict[str, Any]:
    """One measure as the page draws it (ADR-0122 decision 4): already expanded, so
    ``field`` holds a key where its declaration held a ``*``, and ``node`` is the path
    of the node its curve stands on. ``axis_to`` is null where its axis ends past its
    own highest reading (ADR-0117)."""
    return {
        "field": measure.field,
        "unit": measure.unit,
        "label": measure.label,
        "node": node,
        "axis_to": measure.axis_to,
    }


def series_to_dict(series: StandingSeries) -> dict[str, Any]:
    """One series of the series read: where it stands, what it is kept under, what
    of it is drawn there, and what it read."""
    return {
        "node": series.node,
        "key": {"type": series.type_name, "mount": series.mount,
                "subject": series.subject},
        "measures": [_measure(measure, node) for measure, node in series.measures],
        "readings": [_reading(placed) for placed in series.readings],
    }


def series_envelope(path: str, series: Sequence[StandingSeries], *,
                    start: datetime | None = None, end: datetime | None = None,
                    version: str = "", engine: str = "",
                    now: datetime | None = None) -> dict[str, Any]:
    """Wrap the series that stand at or beneath ``path`` in the answer of the series
    read (ADR-0122 decision 6).

    ``schema_version``, ``generated_at`` and ``instance`` are the status read's.
    ``path`` is the node asked, ``/`` for the root, and ``window`` the two instants
    the server read the URL's ``from`` and ``to`` as — ``start`` and ``end``, each
    null where the URL left it to what is kept — because a window back from now is
    read by the server's clock, and the answer says which instants it meant.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": instants.stamp(now or instants.now()),
        "instance": {"version": version, "engine": engine},
        "path": path,
        "window": {"from": None if start is None else instants.stamp(start),
                   "to": None if end is None else instants.stamp(end)},
        "series": [series_to_dict(one) for one in series],
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
    ``None``. Tokens are compared in constant time (ADR-0080 decision 8), through
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
