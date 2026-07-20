"""Extreme-case status-tree fixtures for the UI prototyping harness (backlog #25).

The local deployment's tree is friendly — a dozen hosts, mostly green. The layout,
overflow and header work of the dashboard-polish phase must be judged against
*extremes*, so this module hand-builds the hard cases: an eruption of linked
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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from little_sister.checks import code
from little_sister.status import StatusCode
from little_sister.tree import StatusSnapshot, StatusTree

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
    the overview, when ``branch`` is empty); the harness renders ``status.html``
    for that node with that breadcrumb. ``engine_error`` renders the page as if
    the engine had failed to start with that reason (the header banner).
    """

    name: str
    description: str
    build: Callable[[], StatusSnapshot]
    branch: str = ""
    engine_error: str | None = None


def _snapshot(tree: StatusTree, branch: str = "",
              now: datetime | None = None) -> StatusSnapshot:
    """Snapshot ``branch`` (root by default); the node always exists here."""
    snap = tree.snapshot(branch, now=now)
    if snap is None:  # pragma: no cover - fixtures always address a real node
        raise AssertionError(f"fixture built no node at {branch!r}")
    return snap


def _hosts_ok(count: int) -> StatusSnapshot:
    """``count`` all-OK leaf hosts — the overview at scale (leaf density, #24)."""
    tree = StatusTree()
    for index in range(1, count + 1):
        tree.upsert(f"/host{index:02d}", StatusCode.OK)
    return _snapshot(tree)


def _eruption() -> StatusSnapshot:
    """A CI host whose ``actions`` leaf lists twelve failed workflows, each a
    link (the github-``actions`` case, #9) — beside two calm neighbours so the
    eruption's effect on the grid is visible."""
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
    text. Beside a calm neighbour so the blast radius on the grid is visible."""
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
    overflow case (#9) — beside a calm neighbour."""
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
    side of the overflow problem (#24)."""
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
    header (title + about) and the card heads all take the strain (#4/#24)."""
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
    built = datetime.now()
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
    # An admin maintenance pin.
    tree.set_maintenance("/under-maintenance", "planned kernel upgrade",
                         expires_at=built + timedelta(days=1), set_by="pan")
    return _snapshot(tree, now=built + timedelta(minutes=20))


def _reasons_graduated() -> StatusSnapshot:
    """Cards carrying 1 / 6 / 7 / 20 reasons side by side — the boundary either
    side of the per-card entry cap (K = 6, ``_status_grid.html``): 1 and 6 render
    whole, 7 and 20 cap to six behind a "show all (N)" (the rest stay in the DOM,
    hidden by CSS)."""
    tree = StatusTree()
    for count in (1, 6, 7, 20):
        reasons = [f"reason line {i} of {count}" for i in range(1, count + 1)]
        tree.upsert(f"/reasons-{count:02d}", StatusCode.ERROR, reasons)
    return _snapshot(tree)


def _empty() -> StatusSnapshot:
    """The empty tree — a root with no children, which renders the
    'No checks reporting yet' hint (the whole overview while the engine is
    deliberately disabled)."""
    return _snapshot(StatusTree())


# --- The "realistic wall" tier: extremes embedded in a populated overview -----
#
# The fixtures above isolate one extreme beside a calm neighbour or two, which
# judges a single card. Real deployments put the extreme *inside a wall of
# roots* — and the wall itself is an extreme once it grows. All content below is
# synthetic (invented hosts, a fake 123456789012 account, `.example` domains).


def _roots_mixed(count: int) -> StatusSnapshot:
    """``count`` top-level nodes in a deterministic mixed state — the
    "what if we have this many roots?" overview. Mostly OK (the everyday wall)
    with WARN/ERROR/stale/idle/maintenance scattered on fixed indices, plus a
    few over-long names so the columns cope with ragged label widths."""
    tree = StatusTree()
    built = datetime.now()
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
    built = datetime.now()
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
    ``little-sister`` heartbeat (now lifted into the status strip, #24), and a
    security card whose ``informational`` severity leaf is **OK yet floods 150
    findings**. Once the skyscraper beside near-empty tiles; with #24 the quiet
    leaf collapses to a chip and the flood moves to its detail page, so it now
    proves the layout *tames* an OK card that would otherwise drown the grid."""
    tree = StatusTree()
    tree.upsert("/github/actions", StatusCode.OK)
    tree.upsert("/github/pull_requests", StatusCode.OK, "6 open")
    tree.upsert("/github/security_advisories", StatusCode.OK)
    tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
    tree.upsert("/wiz/critical", StatusCode.OK)
    tree.set_title("/wiz/critical", "Critical")
    tree.upsert("/wiz/high", StatusCode.OK)
    tree.set_title("/wiz/high", "High")
    tree.upsert("/wiz/informational", StatusCode.OK,
                [_finding(i) for i in range(1, 151)])
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
    Fixture("deep_tree_depth_8", "a branch nested to depth 8", _deep_tree),
    Fixture("long_names_titles",
            "long names, ellipsable title, long about on a branch head",
            _long_text, branch=_LONG_HOST),
    Fixture("idle_maintenance_stale_mix",
            "live + stale + idle (UNDEFINED) + maintenance", _idle_mix),
    Fixture("reasons_graduated",
            "cards with 1/6/7/20 reasons (reason-cap boundary material)",
            _reasons_graduated),
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
    Fixture("security_findings_150",
            "an OK severity leaf flooding 150 long findings beside near-empty "
            "tiles (the wiz screenshot case)", _security_findings),
    Fixture("unbreakable_tokens",
            "single-token reasons: ~300-char URL, image digest, 500-char "
            "code() line (width overflow)", _unbreakable_tokens),
)

FIXTURES_BY_NAME: dict[str, Fixture] = {f.name: f for f in FIXTURES}
