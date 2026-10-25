"""Extreme-case status-tree fixtures for the UI harness (testing-the-gui.md).

The local deployment's tree is friendly — a dozen hosts, mostly green. Layout,
overflow and header work has to be judged against *extremes*, so this module
hand-builds the hard cases: an eruption of linked
reasons, a huge ``code()`` reason, deep and wide trees, long names/titles, a
staleness/maintenance/idle mix, and the empty engine-down tree — plus a
"realistic wall" tier that embeds the extremes in a *populated* overview: an
80-root mixed wall, a multi-front incident, an OK card flooding 150 audit
findings (the wiz case), and unbreakable single-token reasons.

Each fixture is produced from a **real** :class:`~little_sister.tree.StatusTree`
and returned as the :class:`~little_sister.tree.StatusSnapshot` the templates
render, so roll-up, staleness and sibling ordering are correct by construction
(``tree.py``) rather than hand-set and possibly inconsistent. Staleness is driven
deterministically by giving a node a ``frequency`` and taking the snapshot at a
chosen ``now`` — never by sleeping.

The render harness (``render_ui_fixtures.py``) feeds these through the real
templates for side-by-side screenshots; ``test_ui_fixtures.py`` renders them as a
smoke test, so the fixtures double as test data.

Dev-only: this module lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from little_sister.checks import Check, CheckResult, Measurement, code
from little_sister.checks.http import HttpCheck
from little_sister.checks.metadata import Stated
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusSnapshot, StatusTree
from tests import anonymized_tree

# A host whose name (and its child's) is deliberately far too long, to stress the
# card head, the header title and the breadcrumb. Kept as a constant so the
# fixture's `branch` can point the header at it.
_LONG_HOST = (
    "very-long-hostname-that-keeps-going-and-going-past-any-reasonable-width-"
    "0123456789abcdef"
)
_LONG_LEAF = "service-with-an-absurdly-long-name-that-will-not-fit-on-one-line-either"


@dataclass(frozen=True)
class Fixture:
    """One named extreme case: how to build its snapshot and where it is viewed.

    ``build`` returns the snapshot of the node named by ``branch`` (the root, i.e.
    the overview, when ``branch`` is empty); the harness normally renders
    ``status.html`` for that node with that breadcrumb. ``detail`` selects the
    member-leaf ``check.html`` surface instead. ``engine_error`` renders the page
    as if the engine had failed to start with that reason (the header banner).
    ``chips`` is the fixture's ``settings.yaml`` word for every level nobody else
    speaks for: unsaid, the built-in look — open, but a big level as chips — and
    ``False`` every level open, the big ones too, so a layout case is drawn whole;
    ``nodes`` its ``nodes.yaml``, each path's look, for a level a case wants closed.
    ``reason_cap`` overrides the harness configuration when a layout case
    specifically exercises a deployment with a taller stable line budget.
    """

    name: str
    description: str
    build: Callable[[], StatusSnapshot]
    branch: str = ""
    engine_error: str | None = None
    detail: bool = False
    chips: bool | None = None
    nodes: Mapping[str, Stated] = field(default_factory=dict)
    reason_cap: int | None = None
    #: What the page is told is reached *through* this node. A registry fact rather
    #: than a snapshot one, so a fixture states it here instead of building it.
    dependents: tuple[str, ...] = ()
    #: What the page asks for the node's series (ADR-0092): an engine holding the
    #: check that keeps it and the readings it kept, never started. An engine fact
    #: rather than a snapshot one, like the dependents above.
    engine: Callable[[], Engine] | None = None


# The sheet is a static artifact, so the *observation* times the cards now carry
# (ADR-0027) must be fixed like ``_RENDERED_AT`` — a build-time ``now`` would make
# every re-run diff. An instant, so the rendered time of day is the configured
# timezone's — 11:59:31 in `Europe/Berlin` — whatever the renderer's own clock is
# set to, which keeps the sheet (and the tests reading it) identical on any machine.
_PINNED_STAMP = datetime(2026, 7, 20, 9, 59, 31, tzinfo=UTC)
#: The armed next slot, pinned for the same reason (ADR-0044). ``_pin_stamps`` does
#: not reach it — the run facts are one object below the snapshot, and a fixture that
#: wants them says so — so it is written straight into the tree.
_PINNED_NEXT_RUN = datetime(2026, 7, 20, 10, 4, tzinfo=UTC)


def _pin_stamps(snap: StatusSnapshot) -> StatusSnapshot:
    """Replace every *present* observation time in the subtree with
    :data:`_PINNED_STAMP`. ``None`` is left alone: a node no check has written — and a
    container above two or more checks — must still render no time at all, which is
    the case the layout has to look right in (ADR-0027)."""
    return replace(
        snap,
        timestamp=None if snap.timestamp is None else _PINNED_STAMP,
        children=tuple(_pin_stamps(child) for child in snap.children))


def _snapshot(tree: StatusTree, branch: str = "",
              now: datetime | None = None) -> StatusSnapshot:
    """Snapshot ``branch`` (root by default); the node always exists here. Every
    fixture funnels through here, so pinning the stamps once covers the whole sheet —
    and so does the one guard a fixture needs since a pin makes no node (ADR-0109
    decision 4): a path it pins is one it wrote. Otherwise its page shows no pinned
    node, and nothing on it says that one is missing."""
    nodes, lines = tree.pins()
    unwritten = sorted(path for path in {*nodes, *(path for path, _slug in lines)}
                       if tree.snapshot(path) is None)
    if unwritten:
        raise AssertionError(
            f"fixture pins what it never wrote: {', '.join(unwritten)}")
    snap = tree.snapshot(branch, now=now)
    if snap is None:  # pragma: no cover - fixtures always address a real node
        raise AssertionError(f"fixture built no node at {branch!r}")
    return _pin_stamps(snap)


def _hosts_ok(count: int) -> StatusSnapshot:
    """``count`` all-OK leaf hosts — the overview at scale (leaf density, ADR-0056)."""
    tree = StatusTree()
    for index in range(1, count + 1):
        tree.upsert(f"/host{index:02d}", StatusCode.OK)
    return _snapshot(tree)


def _eruption() -> StatusSnapshot:
    """A CI host whose ``actions`` leaf lists twelve failed workflows, each a
    link (the github-``actions`` case for the reason budget, ADR-0056) — beside
    two calm neighbors so the eruption's effect on the grid is visible."""
    tree = StatusTree()
    tree.upsert("/web", StatusCode.OK)
    tree.upsert("/db", StatusCode.OK)
    workflows = [
        "unit", "integration", "lint", "typecheck", "e2e-chrome", "e2e-firefox",
        "docker-build", "release", "docs", "coverage", "security-scan",
        "deploy-staging",
    ]
    reasons = [
        f"[build #{2000 + i} · {name}](https://ci.example/runs/{2000 + i}) failed"
        for i, name in enumerate(workflows)
    ]
    tree.upsert("/ci/actions", StatusCode.ERROR, reasons)
    return _snapshot(tree)


def _long_link_eruption() -> StatusSnapshot:
    """A CI ``nightly`` leaf reporting **100** failed jobs, each a long link — a
    real deployment case (a check that emits ~100 reason lines with long links).
    The reason list at its worst: many entries *and* wide, hard-to-break link
    text. Beside a calm neighbor so the blast radius on the grid is visible."""
    tree = StatusTree()
    tree.upsert("/web", StatusCode.OK)
    reasons = [
        f"[build-and-test / matrix (ubuntu-24.04, py3.14, shard {i:03d}/100) "
        f"· run #{8_000_000_000 + i * 137}]"
        f"(https://ci.example.com/andro-meda/little-sister/actions/"
        f"runs/{8_000_000_000 + i * 137}/jobs/{30_000_000_000 + i * 911}) "
        f"failed after {20 + i % 40}m"
        for i in range(1, 101)
    ]
    tree.upsert("/ci/github-actions/nightly", StatusCode.ERROR, reasons)
    return _snapshot(tree)


def _code_reason() -> StatusSnapshot:
    """A single 200-line ``code()`` reason (a captured traceback) — the vertical
    overflow case for the reason budget (ADR-0056) — beside a calm neighbor."""
    tree = StatusTree()
    tree.upsert("/web", StatusCode.OK)
    lines = "\n".join(
        f"{i:>3}  File \"/opt/app/module_{i}.py\", line {i * 7}, in handler"
        for i in range(1, 201)
    )
    tree.upsert("/app/trace", StatusCode.ERROR, code(lines))
    return _snapshot(tree)


def _wide_host() -> StatusSnapshot:
    """One NAS host with fifteen leaf disks in a mixed state — the many-children
    side of the overflow problem (ADR-0056)."""
    tree = StatusTree()
    pattern = [
        StatusCode.OK, StatusCode.OK, StatusCode.WARN, StatusCode.OK,
        StatusCode.OK, StatusCode.ERROR, StatusCode.OK, StatusCode.OK,
    ]
    for index in range(1, 16):
        status = pattern[index % len(pattern)]
        reason = None if status is StatusCode.OK else f"disk{index:02d} degraded"
        tree.upsert(f"/nas/disk{index:02d}", status, reason)
    return _snapshot(tree)


def _branchy_host() -> StatusSnapshot:
    """One NAS host whose card stacks several all-OK sub-*branches* — each a boxed
    chip-row (``disk`` / ``smart`` / ``system`` …), its leaves chips as the NAS's type
    proposes them (the fixture's ``nodes``) — the branch-density case (ADR-0056):
    every sub-branch stands as its box, the one erupting among them, its failure
    opening its way. Beside a calm neighbor so the card's effect on the grid is
    visible."""
    tree = StatusTree()
    tree.upsert("/web", StatusCode.OK)
    aspects = {
        "disk": ("sda", "sdb", "sdc", "sdd"),
        "smart": ("sda", "sdb", "sdc", "sdd"),
        "system": ("cpu", "load", "memory", "uptime"),
        "temperature": ("board", "cpu", "drive-bay"),
        "network": ("eth0", "eth1"),
        "power": ("psu0", "psu1"),
    }
    for aspect, leaves in aspects.items():
        for leaf in leaves:
            tree.upsert(f"/qnap/{aspect}/{leaf}", StatusCode.OK)
    # One aspect erupts: its box stays put, its failing leaf opened by the budget.
    tree.upsert("/qnap/fans/rpm-fan2", StatusCode.ERROR, "fan 2 stalled (0 rpm)")
    return _snapshot(tree)


def _deep_tree() -> StatusSnapshot:
    """A single branch nested to depth eight (the render depth ceiling,
    ``MAX_DEPTH``) — recursive-nesting overflow."""
    tree = StatusTree()
    path = "/" + "/".join(f"level{i}" for i in range(1, 9))
    tree.upsert(path, StatusCode.ERROR, "the leaf eight levels down is unhealthy")
    return _snapshot(tree)


def _long_text() -> StatusSnapshot:
    """A host with an over-long name, an over-long child name, an ellipsable
    title and a long ``about`` on the branch head — viewed at the branch so the
    header (title + about) and the card heads all take the strain (ADR-0056)."""
    tree = StatusTree()
    leaf = f"/{_LONG_HOST}/{_LONG_LEAF}"
    tree.upsert(leaf, StatusCode.WARN,
                "a reason that is itself very long and keeps describing the "
                "problem well past the point where a card would like to wrap it")
    tree.set_title(f"/{_LONG_HOST}",
                   "A very long human-friendly title that ought to ellipse "
                   "rather than shove the status chip off the right edge")
    tree.set_about(
        f"/{_LONG_HOST}",
        "A deliberately long **about** paragraph on the branch head. " * 6)
    return _snapshot(tree, _LONG_HOST)


def _idle_mix() -> StatusSnapshot:
    """Live OK/WARN/ERROR beside a stale node, an idle (UNDEFINED, never-reported)
    node and a maintenance pin — the idle/stale/maintenance treatments together
    (freshness, ADR-0005; #26)."""
    tree = StatusTree()
    built = datetime.now(UTC)
    # Long frequency ⇒ still fresh 20 min on; these carry live status.
    tree.upsert("/live-ok", StatusCode.OK, frequency_seconds=3600)
    tree.upsert("/live-warn", StatusCode.WARN, "elevated latency",
                frequency_seconds=3600)
    tree.upsert("/live-error", StatusCode.ERROR, "connection refused",
                frequency_seconds=3600)
    # Short frequency ⇒ stale at the snapshot `now` below (degrades to WARN).
    tree.upsert("/gone-stale", StatusCode.OK, frequency_seconds=60)
    # Metadata-only node: never reported, so it stays UNDEFINED (idle).
    tree.set_about("/never-reported", "a check that has not run yet")
    # An admin maintenance pin, on a node its check reads.
    tree.upsert("/under-maintenance", StatusCode.OK, frequency_seconds=3600)
    tree.set_maintenance("/under-maintenance", "planned kernel upgrade",
                         expires_at=built + timedelta(days=1), set_by="pan")
    return _snapshot(tree, now=built + timedelta(minutes=20))


def _observation_times() -> StatusSnapshot:
    """The observation-time roll-up as the cards show it (ADR-0027), both outcomes
    side by side: ``solo`` covers exactly **one** check, so the container inherits that
    check's run time and its card carries a time; ``pair`` covers **two**, so no single
    value could answer for both and its card carries **none**. ``never-run`` is a
    registered mount that has not reported yet — registration is not an observation, so
    that card is bare too. The absence is the point, and this is the layout case where
    a card in the wall has no time while its neighbors do."""
    tree = StatusTree()
    for path in ("/solo/host_metrics", "/pair/host_metrics", "/pair/audit"):
        tree.set_check_mount(path)
        tree.upsert(path, StatusCode.OK, frequency_seconds=3600)
    tree.set_check_mount("/never-run/host_metrics")
    tree.set_about("/never-run", "a host whose only check has not reported yet")
    return _snapshot(tree)


def _node_facts() -> StatusSnapshot:
    """The **branch page's** node-facts block (ADR-0044 decision 8) at the size that
    decided its placement: a container owned by one check, so it carries run facts,
    its ``config`` and a ``report`` — and the report is a forty-name roster, which is
    the volume the block was put *below* the child grid for. The layout question is
    whether the dashboard still reads as a dashboard with all that under it, and
    whether the 820px block sits right beside a full-width grid."""
    tree = StatusTree()
    tree.set_check_mount("/quality/github")
    tree.upsert("/quality/github", StatusCode.OK, frequency_seconds=300,
                config=("- **scope:** andro-meda\n- **name prefix:** little-\n"
                        "- **archived:** excluded\n- **team:** platform"),
                report=("**40 repositories** in scope — a roster, carrying no "
                        "verdicts: a repository acquires a claim only when "
                        "something is wrong with it, and that claim is a reason.\n\n"
                        + "\n".join(f"- `little-sister-{name}`" for name in (
                            "app", "agent", "stress", "docs", "ansible",
                            "charts", "cli", "client-ios", "client-macos",
                            "dashboards", "demo", "e2e", "fixtures", "gateway",
                            "helm", "infra", "lint", "metrics", "notify",
                            "operator", "playbooks", "probe", "proxy", "release",
                            "runner", "satellite", "schemas", "scripts", "sdk",
                            "shell", "site", "snapshots", "spec", "ssh", "stubs",
                            "themes", "tools", "vault", "web", "workers"))))
    tree.upsert("/quality/github/actions", StatusCode.OK)
    tree.upsert("/quality/github/pull_requests", StatusCode.WARN,
                ["#4821 Bump ruff to 0.6.9 — waiting 21h for a reviewer"])
    tree.set_run_facts("/quality/github", wall_seconds=1.42,
                       next_run_at=_PINNED_NEXT_RUN)
    return _snapshot(tree, branch="quality/github")


def _maintenance_deep() -> StatusSnapshot:
    """An admin pin sits **deep** in a card (``nexus/disk/smart/bay-7``), where the
    roll-up and a shallow depth hide it — the maintenance-surfacing case (ADR-0014):
    the strip **pill**'s popover lists it by path with time left, and the ``nexus`` card
    gains a "contains maintenance" pip. Beside two calm hosts."""
    tree = StatusTree()
    built = datetime.now(UTC)
    tree.upsert("/web", StatusCode.OK)
    tree.upsert("/db", StatusCode.OK)
    tree.upsert("/nexus/disk/smart/bay-1", StatusCode.OK)
    tree.upsert("/nexus/disk/smart/bay-2", StatusCode.OK)
    tree.upsert("/nexus/disk/smart/bay-7", StatusCode.WARN, "reallocated sectors: 12")
    tree.set_maintenance("/nexus/disk/smart/bay-7", "disk swap (RMA 4471)",
                         expires_at=built + timedelta(days=2, hours=6), set_by="pan")
    return _snapshot(tree, now=built + timedelta(minutes=1))


def _maintenance_many() -> StatusSnapshot:
    """Twelve admin pins scattered across the tree — past the popover's
    ``maintenance_cap`` (5 by default), the case the count folds away: the strip
    **pill** reads "12 in maintenance", its popover lists the first five and folds
    the rest behind a "+7 more" link to *Handled*, **/handled**. Varied
    depths, reasons and expiries exercise the page's path column and the coarse
    "time left" (days, hours, minutes). Beside the ``little-sister`` heartbeat and
    a few calm hosts, so the pill's place in the strip band — just left of the
    heartbeat — is visible."""
    tree = StatusTree()
    built = datetime.now(UTC)
    tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
    for index in range(1, 5):
        tree.upsert(f"/host{index:02d}", StatusCode.OK, frequency_seconds=3600)
    # Twelve pins: several share a rack ancestor (one card pip then covers a few),
    # others stand alone, across a spread of depths, reasons and expiries.
    pins = (
        ("/rack-a/shelf1/bay-03", "disk swap (RMA 4471)", timedelta(days=2, hours=6)),
        ("/rack-a/shelf1/bay-09", "disk swap (RMA 4472)", timedelta(days=1, hours=2)),
        ("/rack-a/shelf2/psu-1", "PSU replacement", timedelta(hours=8)),
        ("/rack-b/node-07/nic-eth1", "cable reseat", timedelta(hours=3, minutes=30)),
        ("/rack-b/node-11", "kernel upgrade", timedelta(days=1)),
        ("/db-primary", "planned failover drill", timedelta(hours=1)),
        ("/db-replica-02", "storage migration", timedelta(days=5)),
        ("/cache/redis-03", "memory bump", timedelta(minutes=45)),
        ("/edge/lb-01", "firmware update", timedelta(hours=12)),
        ("/edge/lb-02", "firmware update", timedelta(hours=12, minutes=30)),
        ("/warehouse/etl/nightly", "pipeline rewrite", timedelta(days=3)),
        ("/sensor-bay/probe-7", "recalibration", timedelta(minutes=20)),
    )
    for path, reason, remaining in pins:
        tree.upsert(path, StatusCode.OK, frequency_seconds=3600)
        tree.set_maintenance(path, reason,
                             expires_at=built + remaining, set_by="pan")
    return _snapshot(tree, now=built + timedelta(minutes=1))


def _maintenance_editor() -> StatusSnapshot:
    """The admin member-leaf interaction: stable controls, one rendered entry pin
    and the whole-node read/edit card on the same page. The explanation deliberately
    carries block Markdown and raw HTML so the sheet exposes both rendering and the
    source textarea's escaping boundary."""
    tree = StatusTree()
    findings = {
        f"finding-{index}": (
            f"[Finding {index}](https://security.example/findings/{index}) — "
            f"package-{index} needs review"
        )
        for index in range(1, 13)
    }
    tree.upsert("/security/audit", StatusCode.ERROR, findings)
    expires = datetime.now(UTC) + timedelta(days=2)
    tree.set_entry_maintenance(
        "/security/audit", "finding-2",
        "**Ada owns this**\n\n- ticket filed\n- patch under review",
        expires_at=expires, set_by="ada")
    tree.set_maintenance(
        "/security/audit",
        "[Change window](https://ops.example/change/42)\n\n"
        "<script>shown as text</script>",
        expires_at=expires, set_by="pan")
    return _snapshot(tree, "security/audit")


def _reasons_graduated() -> StatusSnapshot:
    """Cards carrying 1 / 6 / 7 / 20 reasons side by side — around the per-card line
    budget (``reason_cap`` = 6 by default): the 1- and 6-reason cards fit, the 7- and
    20-reason cards overflow it and clip behind the header chevron (the rest stay in
    the DOM, faded by CSS)."""
    tree = StatusTree()
    for count in (1, 6, 7, 20):
        reasons = [f"reason line {i} of {count}" for i in range(1, count + 1)]
        tree.upsert(f"/reasons-{count:02d}", StatusCode.ERROR, reasons)
    return _snapshot(tree)


def coded_workflow_tree() -> StatusTree:
    """The coded-entry tree behind both coded fixtures — and the one the contrast
    sweep serves, so Mode 1 and Mode 4 judge the same roster (testing-the-gui.md).

    Coded entry lines (ADR-0042) in every state at once, beside a calm neighbor: a
    failed workflow already re-running (error tint + italic), a healthy line (pale
    ok tint — green under the red card), a healthy line rebuilding (ok tint +
    italic), a queued line (warn tint), one that has never concluded (ring cue on
    the undefined tint), a pinned coded line wearing the maintenance tint over its
    own state, and an uncoded advisory carrying the node's code. The node derives
    ERROR from its lines; the reported code beneath the pin stays visible on the
    leaf page.

    The two warn lines are the point of the ordering: a pin's quiet tint outranks
    the code it covers, so the *pinned* line cannot also show what a warn line looks
    like — with one line each, both are on the sheet. Seven lines against a
    ``reason_cap`` of six also means the uncoded advisory folds on the overview and
    shows on the leaf page, which is where an uncoded line matters anyway (on the
    card it is ordinary reason ink, measured from the tokens by
    ``tests/test_contrast.py``)."""
    tree = StatusTree()
    tree.upsert("/ci/actions", StatusCode.ERROR, [
        Entry("web-build",
              "web (main) / build: failed after 8m14s \u00b7 #4216 running 2m",
              StatusCode.ERROR, running=True),
        Entry("api-tests", "api (main) / tests: passed in 2m01s",
              StatusCode.OK),
        Entry("docs-build", "docs (main) / build: passed in 41s \u00b7 #911 "
              "running 12s", StatusCode.OK, running=True),
        Entry("release-queue", "release (main) / publish: queued behind 3 jobs",
              StatusCode.WARN),
        Entry("nightly-audit", "nightly / audit: has never completed",
              StatusCode.UNDEFINED),
        Entry("deploy-gate", "deploy (main) / gate: waiting for approval",
              StatusCode.WARN),
        Entry("quota-note", "runner minutes at 61% of the monthly quota"),
    ])
    tree.upsert("/ci/lint", StatusCode.OK)
    tree.set_entry_maintenance(
        "/ci/actions", "deploy-gate",
        "approvals paused for the release freeze",
        expires_at=datetime.now(UTC) + timedelta(days=2), set_by="ada")
    return tree


def _coded_workflows() -> StatusSnapshot:
    """The coded-entry roster as the templates render it (see
    :func:`coded_workflow_tree`)."""
    return _snapshot(coded_workflow_tree())


def _shielded_unit() -> StatusSnapshot:
    """A unit behind a failed gateway: red on its own page, reaching nothing above
    it. The page has to say *why* it is quiet upward and *where* to go — a sheet
    that shows only the red card is the case an operator misreads."""
    tree = StatusTree()
    tree.upsert("/net/vpn", StatusCode.ERROR, "the tunnel is down")
    tree.upsert("/svc/api", StatusCode.ERROR, "connect: no route to host",
                frequency_seconds=300)
    tree.set_dependency("/svc/api", "/net/vpn")
    return _snapshot(tree, branch="svc/api")


def _gateway() -> StatusSnapshot:
    """The other end: what the page says on a node dozens of checks are reached
    through, while it is the thing that failed."""
    tree = StatusTree()
    tree.upsert("/net/vpn", StatusCode.ERROR, "the tunnel is down",
                frequency_seconds=60)
    for name in ("api", "db", "queue", "web"):
        tree.upsert(f"/svc/{name}", StatusCode.ERROR)
        tree.set_dependency(f"/svc/{name}", "/net/vpn")
    return _snapshot(tree, branch="net/vpn")


def _record_times() -> StatusSnapshot:
    """A leaf whose lines carry records and whose run measured one: both lists the
    node's own page shows (`_record_list.html`). A Lambda function's line reads its
    `at` in the configured zone, a batch job's run its nested `created.at` and its
    `started` beside a null `ended` (it is still running), and what is not a time
    the zone can hold is shown as stored — a time-shaped string under a name the
    seam does not type, and the last half hour of the calendar. The measured record
    carries an `at` of its own, so the Measured card reads the same way. The times
    sit a few minutes before the sheet's pinned observation (ADR-0027)."""
    tree = StatusTree()
    tree.upsert("/aws/account", StatusCode.OK, [
        Entry("batch-nightly-reindex", "nightly / reindex: running for 12m",
              StatusCode.OK, running=True, subject="batch/nightly/reindex",
              data={"queue": "nightly", "name": "reindex", "status": "RUNNING",
                    "created": {"at": "2026-07-20T09:40:00Z"},
                    "started": "2026-07-20T09:47:31Z", "ended": None,
                    "at": None, "cache_key": "2026-07-20T09:40:00Z"}),
        Entry("lambda-resize-images", "resize-images: no errors, last run 21m ago",
              StatusCode.OK, subject="lambda/resize-images",
              data={"name": "resize-images", "errors": 0,
                    "at": "2026-07-20T09:38:00Z", "log_status": None}),
        Entry("retention-archive", "archive / retention: kept to the end of time",
              StatusCode.OK, data={"bucket": "archive",
                                   "at": "9999-12-31T23:30:00Z"}),
    ], members=True, subject="account/eu-central-1",
        record={"regions": 1, "functions": 1, "queues": 1,
                "at": "2026-07-20T09:59:31Z"})
    return _snapshot(tree, branch="aws/account")


def _refused_records() -> StatusSnapshot:
    """A leaf whose check read three workflows in one run and whose seam refused two
    records (ADR-0093), as the engine leaves the node: a line that stands as its
    grading wrote it, its record refused for its weight and said so where the record
    would be; a reading refused for a time without its offset, kept out of the
    grading and reported on the node by the engine at WARN, naming the subject and
    why; and a line whose record passed, listed as usual."""
    tree = StatusTree()
    tree.upsert("/ci/actions", StatusCode.WARN, [
        Entry("refused-octo-web",
              "the record of octo/web was refused, and not graded: "
              "'completed.at' names a time, and '2026-07-20T09:12:00' is not one "
              "with an offset",
              StatusCode.WARN, subject="octo/web"),
        Entry("octo-api-ci-main", "octo/api (main) / CI: passed (#128)",
              StatusCode.OK, subject="octo/api",
              data={"repository": "octo/api", "workflow": "CI", "branch": "main",
                    "run_number": 128,
                    "completed": {"at": "2026-07-20T09:41:00Z"}}),
        Entry("octo-docs-deploy-main", "octo/docs (main) / deploy: passed (#12)",
              StatusCode.OK, subject="octo/docs",
              refused="it is 2,811 bytes and the limit is 2,048"),
    ], members=True, frequency_seconds=300)
    return _snapshot(tree, branch="ci/actions")


#: The plan's first curve: one site, read every three minutes, a day of it kept.
_SITE = "https://www.example.org"
#: The newest reading sits a few minutes before the sheet's pinned observation.
_SERIES_END = datetime(2026, 7, 20, 9, 57, tzinfo=UTC)


def _site_node() -> StatusSnapshot:
    """An `http` leaf whose node stands for its URL (ADR-0086), as the newest run
    left it: the reading it placed, the line that retells it, the configuration it
    ran with. The Readings card under it is the series (``_site_engine``)."""
    tree = StatusTree()
    tree.upsert("/web/site", StatusCode.OK,
                [Entry("response", "HTTP 200 in 212 ms")],
                frequency_seconds=180, subject=_SITE,
                record={"status": 200, "response_ms": 212},
                config=f"- **url:** {_SITE}\n- **expected status:** 200\n"
                       "- **redirects:** followed")
    return _snapshot(tree, branch="web/site")


def _site_engine() -> Engine:
    """Eight hours of that site, every three minutes, as its series keeps them —
    the shapes the curve has to tell apart: a burst of three requests that failed
    and one that failed alone (a marked break each), an hour and a half in which
    the machine was asleep (a plain break), the slow first answer after it
    (1.9 s — the unit's second rung), and the quiet noise in between."""
    check = HttpCheck.from_config(
        {"type": "http", "path": "/web/site", "url": _SITE, "frequency": "3m",
         "series_keep": 480}, Path("."))
    store = MemoryStore()
    noise = random.Random(20260720)
    start = _SERIES_END - timedelta(hours=8)
    asleep = (start + timedelta(hours=2, minutes=33),
              start + timedelta(hours=4, minutes=3))
    failed = {start + timedelta(hours=5, minutes=m) for m in (15, 18, 21)}
    failed.add(start + timedelta(hours=6, minutes=36))
    woke = asleep[1] + timedelta(minutes=3)
    for step in range(161):
        at = start + timedelta(minutes=3 * step)
        if asleep[0] <= at <= asleep[1]:
            continue
        if at in failed:
            record: dict[str, object] = {
                "status": None, "response_ms": None,
                "error": "request failed for GET https://www.example.org: timed out"}
            said = "request failed: timed out"
        else:
            wave = 60 * math.sin(step / 14)
            response_ms = (1864 if at == woke
                           else round(190 + wave + noise.gauss(0, 22)))
            record = {"status": 200, "response_ms": response_ms}
            said = f"HTTP 200 in {response_ms} ms"
        store.add(SeriesKey("http", "/web/site", _SITE),
                  SeriesRecord(record, at,
                               code=(StatusCode.ERROR if at in failed
                                     else StatusCode.OK),
                               texts=(said,)),
                  keep=check.series_keep)
    return Engine([check], StatusTree(), series=store)


class _HostReading(Check):
    """A host check that keeps its readings, for the branch page's Readings card:
    its measures are the deployment's, stated as the YAML would state them."""

    type_name = "fixture-host"

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


def _host_node() -> StatusSnapshot:
    """A host branch whose node stands for the machine it read (ADR-0086), with its
    children beneath: on the branch page the node's facts — the Readings card among
    them — stand under the child grid, and the poll renders them again."""
    tree = StatusTree()
    tree.upsert("/hosts/nas", StatusCode.OK, frequency_seconds=60, subject="nas1",
                record={"load": 0.42, "memory": {"used_pct": 61}})
    tree.upsert("/hosts/nas/disk", StatusCode.OK, "3 of 4 volumes above 70 %",
                frequency_seconds=60)
    tree.upsert("/hosts/nas/memory", StatusCode.OK, "61 % in use",
                frequency_seconds=60)
    return _snapshot(tree, branch="hosts/nas")


def _host_engine() -> Engine:
    """Ninety minutes of that host, a reading a minute: two measures, so two curves
    one above the other — never one chart with two scales — the load without a unit
    and the memory in `%`, which labels its axis once."""
    check = _HostReading(
        path="/hosts/nas", subject="nas1", frequency_seconds=60, series_keep=120,
        measures={"load": {"unit": "", "label": "Load average"},
                  "memory.used_pct": {"unit": "%", "label": "Memory in use"}})
    store = MemoryStore()
    start = _SERIES_END - timedelta(minutes=90)
    for step in range(91):
        at = start + timedelta(minutes=step)
        load = round(0.35 + 0.25 * math.sin(step / 9) + 0.04 * (step % 5), 2)
        used = 52 + step // 10
        store.add(SeriesKey("fixture-host", "/hosts/nas", "nas1"),
                  SeriesRecord({"load": load, "memory": {"used_pct": used}}, at,
                               code=StatusCode.OK,
                               texts=(f"load {load}, memory {used} %",)),
                  keep=check.series_keep)
    return Engine([check], StatusTree(), series=store)


_JOB = "queue-live/transform"
_WORKFLOW = "100200300:4005006:main"


def _runs_node(path: str, subject: str, said: str, record: dict[str, object]
               ) -> Callable[[], StatusSnapshot]:
    """A leaf whose node stands for a subject with a history of runs (ADR-0106): the
    job name or the workflow its check declares, as its newest run left it. The
    Series card under it is its runs (``_runs_engine``)."""
    def build() -> StatusSnapshot:
        tree = StatusTree()
        tree.upsert(path, StatusCode.OK, [Entry("newest", said)],
                    frequency_seconds=300, subject=subject, record=record)
        return _snapshot(tree, branch=path.strip("/"))
    return build


def _runs_engine(path: str, subject: str, *, timed: bool) -> Callable[[], Engine]:
    """Thirty days of that subject's runs as its series keeps them, each a record
    with an identity (ADR-0111) — the marks a plot of runs has to tell apart: the
    oldest kept no verdict, as a run no line carried keeps none; one failed after
    six minutes and its second attempt ran the same hour; the run time creeps past
    the hour its configuration allows, so the newest nightly runs warned; and since
    four days it runs every two hours, a crowd in which a passing run's head gives
    way. ``timed`` says whether a run carries its run time, which the check's
    measure draws as a stem; without it a run is a tick."""
    def build() -> Engine:
        check = _HostReading(
            path=path, subject=subject, frequency_seconds=300, series_keep=200,
            measures=({"seconds": {"unit": "s", "label": "Run time"}}
                      if timed else {}))
        store = MemoryStore()
        start = _SERIES_END - timedelta(days=30)

        def ran(at: datetime, seconds: int, code: StatusCode | None) -> None:
            outcome = {StatusCode.ERROR: "failed", StatusCode.WARN: "slow"}.get(
                code, "succeeded") if code else "succeeded"
            record: dict[str, object] = {"outcome": outcome, "at": at.isoformat()}
            if timed:
                record["seconds"] = seconds
            store.add(SeriesKey("fixture-host", path, subject),
                      SeriesRecord(record, at, identity=at.isoformat(), code=code,
                                   texts=(() if code is None
                                          else (f"{outcome} in {seconds}s",))),
                      keep=check.series_keep)

        for night in range(26):
            at = start + timedelta(days=night, hours=3)
            seconds = 2500 + 42 * night
            if night == 17:
                ran(at, 360, StatusCode.ERROR)
                ran(at + timedelta(minutes=40), seconds, StatusCode.OK)
                continue
            ran(at, seconds, None if night < 9
                else StatusCode.WARN if seconds > 3500 else StatusCode.OK)
        for step in range(48):
            at = start + timedelta(days=26, hours=2 * step)
            seconds = round(2800 + 240 * math.sin(step * 1.7))
            code = StatusCode.OK
            if step in (9, 30):
                seconds, code = 420, StatusCode.ERROR
            elif step in (17, 41):
                seconds, code = 3900, StatusCode.WARN
            ran(at, seconds, code)
        return Engine([check], StatusTree(), series=store)
    return build


def _empty() -> StatusSnapshot:
    """The empty tree — a root with no children, which renders the
    'No checks reporting yet' hint (the whole overview while the engine is
    deliberately disabled)."""
    return _snapshot(StatusTree())


# --- The "realistic wall" tier: extremes embedded in a populated overview -----
#
# The fixtures above isolate one extreme beside a calm neighbor or two, which
# judges a single card. Real deployments put the extreme *inside a wall of
# roots* — and the wall itself is an extreme once it grows. All content below is
# synthetic (invented hosts, a fake 123456789012 account, `.example` domains).


def _roots_mixed(count: int) -> StatusSnapshot:
    """``count`` top-level nodes in a deterministic mixed state — the
    "what if we have this many roots?" overview. Mostly OK (the everyday wall)
    with WARN/ERROR/stale/idle/maintenance scattered on fixed indices, plus a
    few over-long names so the columns cope with ragged label widths."""
    tree = StatusTree()
    built = datetime.now(UTC)
    for index in range(1, count + 1):
        name = (f"svc-{index:02d}-with-a-name-that-runs-long"
                if index % 17 == 0 else f"host{index:02d}")
        if index % 23 == 0:            # a couple of live ERRORs
            tree.upsert(f"/{name}", StatusCode.ERROR, "probe failed",
                        frequency_seconds=3600)
        elif index % 11 == 0:          # sprinkled WARNs
            tree.upsert(f"/{name}", StatusCode.WARN, "degraded",
                        frequency_seconds=3600)
        elif index % 13 == 0:          # reported once, then fell silent → stale
            tree.upsert(f"/{name}", StatusCode.OK, frequency_seconds=60)
        elif index % 29 == 0:          # metadata only, never reported → idle
            tree.set_about(f"/{name}", "provisioned, check not yet enabled")
        else:
            tree.upsert(f"/{name}", StatusCode.OK, frequency_seconds=3600)
    tree.set_maintenance("/host05", "planned disk swap",
                         expires_at=built + timedelta(days=1), set_by="pan")
    return _snapshot(tree, now=built + timedelta(minutes=20))


def _wall_incident() -> StatusSnapshot:
    """A bad night on a populated wall: sixteen calm hosts *plus* every extreme
    at once — a 12-link eruption, a 200-line ``code()`` trace, a stale host, an
    idle node, a maintenance pin and a deep branch. The layout question this
    asks is not "does one big card render" but "what do three simultaneous
    skyscrapers do to the rows between them"."""
    tree = StatusTree()
    built = datetime.now(UTC)
    for index in range(1, 17):
        tree.upsert(f"/host{index:02d}", StatusCode.OK, frequency_seconds=3600)
    reasons = [
        f"[nightly / job {i:02d} (shard {i}/12)]"
        f"(https://ci.example/runs/{7000 + i}) failed"
        for i in range(1, 13)
    ]
    tree.upsert("/ci/actions", StatusCode.ERROR, reasons)
    lines = "\n".join(
        f"{i:>3}  File \"/opt/app/module_{i}.py\", line {i * 7}, in handler"
        for i in range(1, 201))
    tree.upsert("/app/trace", StatusCode.ERROR, code(lines))
    tree.upsert("/gone-stale", StatusCode.OK, frequency_seconds=60)
    tree.set_about("/never-reported", "a check that has not run yet")
    tree.set_maintenance("/host07", "planned kernel upgrade",
                         expires_at=built + timedelta(days=1), set_by="pan")
    tree.upsert("/rack/shelf/box/probe", StatusCode.WARN,
                "the leaf four levels down is degraded")
    return _snapshot(tree, now=built + timedelta(minutes=20))


def _two_large_roots() -> StatusSnapshot:
    """Two tall top-level branches with differently shaped descendants.

    This is the sparse-root / high-count-subtree case: a wide viewport has room for
    several ordinary cards, but only two roots exist, so the current grid leaves
    the remaining tracks empty while both cards grow downward.  The fixture keeps
    the content synthetic while matching that geometry closely enough to judge
    whether spare width should stay outside the roots or be spent inside them.
    """
    tree = StatusTree()

    tree.upsert("/quality/github/actions", StatusCode.ERROR,
                ["quality-kit (main) / lint failed (#1297)"])
    for band in ("critical", "error", "high", "low", "medium", "note", "warning"):
        tree.upsert(f"/quality/github/code-scanning/{band}", StatusCode.OK)
    tree.upsert("/quality/github/issues", StatusCode.OK, "6 open issues")
    tree.upsert(
        "/quality/github/pull-requests",
        StatusCode.WARN,
        [f"dependency update {index:02d} is waiting for review"
         for index in range(1, 13)],
    )
    tree.upsert("/quality/github/releases", StatusCode.WARN,
                "two release branches have not been tagged")

    for index in range(1, 8):
        status = StatusCode.WARN if index in (2, 6) else StatusCode.OK
        reason = (f"dependency advisory {index:02d} needs review"
                  if status is StatusCode.WARN else None)
        tree.upsert(f"/quality/github/dependency-alerts/advisory-{index:02d}",
                    status, reason)
    for platform in ("linux-311", "linux-314", "macos-arm", "macos-intel",
                     "windows-311", "windows-314", "docs"):
        status = StatusCode.ERROR if platform == "windows-314" else StatusCode.OK
        reason = "the compatibility job failed" if status is StatusCode.ERROR else None
        tree.upsert(f"/quality/github/test-matrix/{platform}", status, reason)

    for environment in ("develop", "infrastructure", "production", "staging"):
        tree.upsert(
            f"/stress/aws/{environment}/cloudwatch/txt-resolve-errors",
            StatusCode.WARN,
            "alarm is active — reports errors in resolve lambda function",
        )
        tree.upsert(
            f"/stress/aws/{environment}/cloudwatch/error-logs-high",
            StatusCode.WARN,
            "reports error-level message count above the expected baseline",
        )
        tree.upsert(
            f"/stress/aws/{environment}/cloudwatch/latency-high",
            StatusCode.WARN,
            "p95 latency is above the synthetic service objective",
        )
        for instance in ("api", "batch", "gateway", "worker"):
            tree.upsert(f"/stress/aws/{environment}/ec2/{instance}", StatusCode.OK)
        tree.upsert(
            f"/stress/aws/{environment}/lambda/read-functions",
            StatusCode.WARN,
            "function inventory cannot be read in this synthetic account",
        )
        tree.upsert(
            f"/stress/aws/{environment}/lambda/process-events",
            StatusCode.WARN,
            "event processor reports a growing retry queue",
        )
        tree.upsert(f"/stress/aws/{environment}/databases/primary", StatusCode.OK)
        tree.upsert(
            f"/stress/aws/{environment}/databases/replica",
            StatusCode.WARN,
            "replication delay exceeds the expected window",
        )

    return _snapshot(tree)


def _two_equal_large_roots() -> StatusSnapshot:
    """Two top-level branches of the *same* size — the live overview's shape.

    ``two_large_roots`` is deliberately lopsided (30 against 66), which is the one
    arrangement where a per-card ``weight / budget`` ceiling still produced a
    proportional split.  A real deployment's roots are often near-equal instead:
    two teams watching the same GitHub aspects, one of them also on WIZ, the other
    on an AWS account set that is currently refusing every AssumeRole and so has
    no aspect children at all.  Both roots then weigh about thirty, both hit the
    ceiling at two tracks, and every further column stays empty however wide the
    viewport is — which is what this fixture holds still.

    The height here comes largely from *reason* lines rather than nodes, which is
    the second half of the same story: a wider card cannot split a node box away
    from its own reasons.
    """
    tree = StatusTree()

    denied = (
        "role cannot be assumed: An error occurred (AccessDenied) when calling "
        "the AssumeRole operation: User: arn:aws:iam::000000000000:user/monitor "
        "is not authorized to perform: sts:AssumeRole on resource: "
        "arn:aws:iam::100000000004:role/application/alarm-monitoring-role"
    )

    for team in ("quality", "stress"):
        tree.upsert(f"/{team}/github/actions", StatusCode.ERROR,
                    [f"{team}_kit (main) / CodeQL: failed (#1297)"])
        for band in ("critical", "error", "high", "low", "medium", "none",
                     "note", "warning"):
            tree.upsert(f"/{team}/github/code_scanning_alerts/{band}",
                        StatusCode.OK)
            tree.upsert(f"/{team}/github/security_advisories/{band}",
                        StatusCode.OK)
        tree.upsert(f"/{team}/github/issues", StatusCode.OK)
        tree.upsert(
            f"/{team}/github/pull_requests", StatusCode.WARN,
            [f"{team}_loadtest-board: Bump the actions group with {index} "
             f"updates [dependabot[bot]]" for index in range(1, 6)],
        )
        tree.upsert(f"/{team}/github/sbom_check", StatusCode.OK)
        tree.upsert(f"/{team}/github/secret_scanning_alerts", StatusCode.OK)

    for band in ("critical", "high", "low", "medium"):
        tree.upsert(f"/quality/wiz/{band}", StatusCode.OK)
    tree.upsert(
        "/quality/wiz/informational", StatusCode.OK,
        [f"{_finding(index)}" for index in range(1, 13)],
    )

    for account in ("backup", "develop", "infrastructure", "live", "staging"):
        tree.upsert(f"/stress/aws/{account}", StatusCode.ERROR, denied)

    return _snapshot(tree)


def _mixed_chip_branches() -> StatusSnapshot:
    """One dense card with chip runs and several boxes at the same level: its level
    starts as chips (the fixture's ``nodes``), and its three branches claim
    ``show_when_quiet``, so they stand open beside the chips of its two leaves.

    Before chip runs became full-row grid items, the direct chips disabled the
    entire nested grid and the three branch boxes stayed stacked however wide
    the card grew.
    """
    tree = StatusTree()
    for branch in ("alpha", "beta", "gamma"):
        for leaf in ("one", "two", "three", "four"):
            tree.upsert(f"/mixed/{branch}/{leaf}", StatusCode.OK)
        tree.set_show_when_quiet(f"/mixed/{branch}", True)
    tree.upsert("/mixed/summary", StatusCode.OK)
    tree.upsert("/mixed/uptime", StatusCode.OK)
    return _snapshot(tree)


def _mixed_nested_flip() -> StatusSnapshot:
    """Fifteen leaf roots plus one root with chains of heights (3,3,3,7,5).

    The shape that ended the universal "wider never gets taller" claim: at the
    width where the mixed card's nested auto-fit flips three columns to four,
    the 7-chain re-chunks beside the 5-chain instead of above it and the card
    genuinely grows — no outer track count can prevent it (all cost more).
    """
    tree = StatusTree()
    for index in range(15):
        tree.upsert(f"/leaf{index:02d}", StatusCode.OK)
    for index, height in enumerate((3, 3, 3, 7, 5)):
        chain = "/".join(f"d{level}" for level in range(height - 1))
        tree.upsert(f"/zmix/c{index}/{chain}" if chain else f"/zmix/c{index}",
                    StatusCode.OK)
    return _snapshot(tree)


def _finding(index: int) -> str:
    """One synthetic security-audit finding line (wiz-shaped, invented data):
    long prose, long unbroken resource identifiers, occasionally a link."""
    stamp = f"2026-07-{(index % 28) + 1:02d}-{index % 24:02d}-{index % 60:02d}"
    resources = (
        f"little-sister-loadtest-{1_700_000_000 + index * 137}-BIGBROTHER-"
        f"{3000 + index}-{index:07x}",
        f"123456789012.dkr.ecr.eu-central-1.registry.example/"
        f"little-sister-testdata-blq{index:04d}"
        f"jvi@sha256:{index * 2654435761 % 10**16:016d}",
        f"postgateway-ag-{index % 40:02d}-{stamp}",
        f"ip-10-0-{index % 256}-{(index * 7) % 256}.eu-central-1.compute.example",
    )
    resource = resources[index % len(resources)]
    templates = (
        f"Resource Running End of Life Software — AWS SDK for Go (v1) ({resource})",
        f"Resource Running End of Life Software — AWS SDK for Java 1.12.780 "
        f"(running-jenkins) {resource}",
        f"VM with kernel vulnerabilities is running a container — {resource}",
        f"SSH key pair is not used by any VM — {resource}",
        f"S3 Bucket with object-level read/write events logging disabled — {resource}",
        f"Resource Running End of Life Software — Spring Framework "
        f"(running-jenkins) {resource}",
    )
    finding = templates[index % len(templates)]
    if index % 10 == 0:
        return f"[{finding}](https://console.example/findings/{index})"
    return finding


def _security_findings() -> StatusSnapshot:
    """The real-deployment screenshot case: three roots — a small branch, the
    ``little-sister`` heartbeat (now lifted into the status strip, ADR-0056), and a
    security card whose ``informational`` severity leaf is **OK yet floods 150
    findings**. Once the skyscraper beside near-empty tiles; the bands start as chips
    as the wiz type proposes them (the fixture's ``nodes``), the flood moved to its
    detail page, so it proves the layout *tames* an OK card that would otherwise
    drown the grid."""
    tree = StatusTree()
    tree.upsert("/github/actions", StatusCode.OK)
    tree.upsert("/github/pull_requests", StatusCode.OK, "6 open")
    tree.upsert("/github/security_advisories", StatusCode.OK)
    tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
    # The severity bands carry a declared rank (ADR-0055): the name sort files
    # `informational` — the band that means *nothing to do* — third, between `high`
    # and `low`. Their titles are deliberately the names again, which is the other
    # half of the same screenshot: no chip should read the word twice.
    tree.upsert("/wiz/critical", StatusCode.OK, order=1)
    tree.set_title("/wiz/critical", "Critical")
    tree.upsert("/wiz/high", StatusCode.OK, order=2)
    tree.set_title("/wiz/high", "High")
    tree.upsert("/wiz/medium", StatusCode.OK, order=3)
    tree.set_title("/wiz/medium", "Medium")
    tree.upsert("/wiz/low", StatusCode.OK, order=4)
    tree.set_title("/wiz/low", "Low")
    tree.upsert("/wiz/informational", StatusCode.OK,
                [_finding(i) for i in range(1, 151)], order=5)
    tree.set_title("/wiz/informational", "Informational")
    tree.set_about("/wiz", "Wiz security issues")
    return _snapshot(tree)


def _unbreakable_tokens() -> StatusSnapshot:
    """Few reasons, each a single unbroken token — the *width* overflow that a
    line cap cannot fix: a ~300-char URL, a container-image digest, a long
    kebab identifier, and a ``code()`` block with one 500-char line (horizontal
    scroll inside the card)."""
    tree = StatusTree()
    tree.upsert("/web", StatusCode.OK)
    url = ("https://artifacts.example/build/" +
           "/".join(f"segment-{i:02d}-0123456789abcdef" for i in range(1, 12)))
    digest = ("registry.example/app@sha256:" + "0123456789abcdef" * 4)
    ident = "-".join(f"part{i:02d}" for i in range(1, 34))
    tree.upsert("/tokens", StatusCode.ERROR, [url, digest, ident])
    tree.upsert("/wide/trace", StatusCode.ERROR,
                code("E " + "x" * 500))
    return _snapshot(tree)


def _anonymized_tree() -> StatusSnapshot:
    """The deployment's tree backlog #91 measured its design on, its names replaced
    (``anonymized_tree.py``): 265 nodes under two teams, the wall as it stands today
    with the deployment's ``reason_cap``. The page the wall's cost is read on, by eye
    here and in numbers in ``test_wall_cost.py`` and ``test_wall_cost_browser.py``.
    The checks' next slot is pinned like every stamp, so the page stays diffable."""
    return _snapshot(anonymized_tree.build(next_run_at=_PINNED_NEXT_RUN))


FIXTURES: tuple[Fixture, ...] = (
    Fixture("hosts_ok_02", "2 hosts, all OK", lambda: _hosts_ok(2)),
    Fixture("hosts_ok_10", "10 hosts, all OK", lambda: _hosts_ok(10)),
    Fixture("hosts_ok_40", "40 hosts, all OK (overview density)",
            lambda: _hosts_ok(40)),
    Fixture("eruption_12_reasons",
            "one node erupting with 12 linked reasons", _eruption),
    Fixture("eruption_100_long_links",
            "one node with 100 long-linked reasons (a real deployment case)",
            _long_link_eruption),
    Fixture("code_reason_200_lines", "a 200-line code() reason", _code_reason),
    Fixture("wide_host_15_leaves", "one host with 15 leaves", _wide_host),
    Fixture("branchy_host_subbranches",
            "one host with 7 sub-branches, one erupting, each a box of chips",
            _branchy_host, nodes={"/qnap": Stated(children=Stated(chips=True))}),
    Fixture("deep_tree_depth_8", "a branch nested to depth 8", _deep_tree),
    Fixture("long_names_titles",
            "long names, ellipsable title, long about on a branch head",
            _long_text, branch=_LONG_HOST),
    Fixture("idle_maintenance_stale_mix",
            "live + stale + idle (UNDEFINED) + maintenance", _idle_mix),
    Fixture("observation_times",
            "the card time under the ADR-0027 roll-up: a container over one check "
            "shows it, over two shows none, a never-run mount shows none",
            _observation_times),
    Fixture("node_facts_branch_head",
            "the branch page's node-facts block: run facts, a forty-name report "
            "and the config block under the child grid",
            _node_facts, branch="quality/github"),
    Fixture("maintenance_deep_pin",
            "an admin pin deep in a card — the strip pill's popover + ancestor pip",
            _maintenance_deep),
    Fixture("maintenance_many_pins",
            "12 pins past the cap — the strip pill, its capped '+N more' popover, "
            "and /handled", _maintenance_many),
    Fixture("maintenance_editor_member_leaf",
            "admin member leaf with rendered node/entry explanations and stable "
            "read-to-edit controls",
            _maintenance_editor, branch="security/audit", detail=True),
    Fixture("reasons_graduated",
            "cards with 1/6/7/20 reasons (reason-cap boundary material)",
            _reasons_graduated),
    Fixture("coded_workflow_lines",
            "coded entry lines (ADR-0042): error+running, ok, ok+running, warn, "
            "never-run and a pinned line — every tint on one card",
            _coded_workflows),
    Fixture("coded_workflow_leaf",
            "the same coded lines on the member leaf page, every state rail, "
            "the uncoded advisory the card folds, and the pinned line's read "
            "mode", _coded_workflows,
            branch="ci/actions", detail=True),
    Fixture("dependency_shield_leaf",
            "a unit behind a failed dependency: red on its own page, reaching "
            "nothing above it, and saying where to go and look",
            _shielded_unit, branch="svc/api", detail=True),
    Fixture("dependency_gateway_leaf",
            "the other end — the failing dependency four checks are reached "
            "through",
            _gateway, branch="net/vpn", detail=True,
            dependents=("/svc/api", "/svc/db", "/svc/queue", "/svc/web")),
    Fixture("record_times_leaf",
            "records on a leaf page: a Lambda line's `at`, a batch run's nested "
            "`created.at` and `started` in the configured zone, a null `ended`, a "
            "time-shaped value under an untyped name and a time past the calendar "
            "as stored, and the measured record read the same way",
            _record_times, branch="aws/account", detail=True),
    Fixture("refused_records_leaf",
            "records the seam refused (ADR-0093): a line that stands without its "
            "record and says why in its place, the engine's WARN line for a "
            "reading kept out of the grading, and a record that passed",
            _refused_records, branch="ci/actions", detail=True),
    Fixture("series_http_leaf",
            "a subject's series on its leaf page (ADR-0092): the response-time "
            "curve with three failed requests and one alone marked, a night's "
            "sleep left plain, and the newest ten readings",
            _site_node, branch="web/site", detail=True, engine=_site_engine),
    Fixture("series_host_branch",
            "the same on a polled branch page: two measures, two curves, the "
            "`%` axis labeled once",
            _host_node, branch="hosts/nas", engine=_host_engine),
    Fixture("runs_stems_leaf",
            "a subject's runs under a measure (ADR-0111): a stem to each run's "
            "run time — the oldest bare and muted, having kept no verdict; a "
            "hollow ring and a lane mark for a failure; the warning's triangle; "
            "and a crowd in which a passing run's head gives way",
            _runs_node("/batch/transform", _JOB, "succeeded in 2936s",
                       {"outcome": "succeeded", "seconds": 2936}),
            branch="batch/transform", detail=True,
            engine=_runs_engine("/batch/transform", _JOB, timed=True)),
    Fixture("runs_ticks_leaf",
            "the same runs without a measure: each a tick whose height says how it "
            "stood, a failure told by its ring and a warning by its triangle",
            _runs_node("/ci/deploy", _WORKFLOW, "succeeded",
                       {"outcome": "succeeded"}),
            branch="ci/deploy", detail=True,
            engine=_runs_engine("/ci/deploy", _WORKFLOW, timed=False)),
    Fixture("empty_engine_down",
            "the empty tree (engine disabled) — the 'No checks' hint", _empty),
    Fixture("engine_error_banner",
            "a failed engine start: the header banner over the empty tree",
            _empty,
            engine_error="checks/web.yaml: unknown check type 'htttp' "
                         "(available: command, file, http, ssh-command, …)"),
    Fixture("roots_80_mixed",
            "80 top-level nodes, mostly OK with scattered trouble (root scale)",
            lambda: _roots_mixed(80)),
    Fixture("wall_incident",
            "16 calm hosts + eruption + 200-line trace + stale/idle/"
            "maintenance + deep branch, all at once", _wall_incident),
    Fixture("two_large_roots",
            "2 tall roots with dozens of differently shaped descendants, "
            "chips off (spare columns)",
            _two_large_roots, chips=False),
    Fixture("two_equal_large_roots",
            "2 tall roots of the *same* weight, chips off — the live overview "
            "shape used to waste width on span steps that opened no columns",
            _two_equal_large_roots, chips=False),
    Fixture("two_equal_large_roots_reason_cap_30",
            "the same 2-root topology with a 30-line reason budget, chips off",
            _two_equal_large_roots, chips=False, reason_cap=30),
    Fixture("mixed_chip_branches",
            "a dense card with a chip run beside 3 branch boxes",
            _mixed_chip_branches, nodes={"/mixed": Stated(chips=True)}),
    Fixture("mixed_nested_flip",
            "15 leaf roots + one card of (3,3,3,7,5) chains, chips off — the "
            "nested column flip no outer track choice can dodge",
            _mixed_nested_flip, chips=False),
    Fixture("security_findings_150",
            "an OK severity leaf flooding 150 long findings beside near-empty "
            "tiles (the wiz screenshot case)", _security_findings,
            nodes={"/wiz": Stated(chips=True)}),
    Fixture("unbreakable_tokens",
            "single-token reasons: ~300-char URL, image digest, 500-char "
            "code() line (width overflow)", _unbreakable_tokens),
    Fixture("anonymized_tree",
            "a deployment's own tree of 265 nodes under two teams, its names "
            "replaced — the wall backlog #91 measures its cost on, reason_cap 30",
            _anonymized_tree, reason_cap=anonymized_tree.REASON_CAP),
)

FIXTURES_BY_NAME: dict[str, Fixture] = {f.name: f for f in FIXTURES}
