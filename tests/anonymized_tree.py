"""The anonymized tree of backlog #91's §3.9: a deployment's tree, its names replaced.

``tests/fixtures/anonymized_tree.json`` is the file the note's prototype drew its boards
from — for each node its path, its code and the lengths of its lines, taken from a real
deployment on 2026-10-10: 265 nodes under two team roots of 98 and 99 leaves, six levels
at the deepest, the widest level 20 repositories with 63 workflows, 234 lines of which
half are under 56 characters while the security check's *informational* band holds
findings over 1,000. The teams are *alpha* and *beta*, every repository, queue, function
and workflow has a generic name, and every line here is made-up text of the recorded
length, so the wall's cost is measured on the deployment's shape without a word of its
own (R13). The file is read by eye and it stays the prototype's: ``test_wall_cost.py``
holds the two copies identical while the prototype is in the tree.

What the shapes do not record is filled in as the deployment has it, generically: the
titles its ``nodes.yaml`` and types give the levels, an *about* on a team and on each
check, the run facts a check's node carries, and which lines are **members** — a
roster's, a finding, an open pull request, a repository without a dependency graph —
so that the wall draws their Copy chips (ADR-0036); a workflow's one line is prose. The
aws type's rosters claim ``show_when_quiet`` (ADR-0063), and the severity bands carry
their declared rank (ADR-0055), as the deployment's do.

Made worse, as §3.9 did it, each a :data:`VARIANTS` key of :func:`build`:

- ``recorded`` — the tree as taken.
- ``outage`` — every workflow of *alpha*'s 20 repositories failing at once.
- ``blackout`` — every leaf failing, a line of 60 characters where it had none.
- ``wide`` — *alpha*'s workflow runs made five times wider: 100 repositories with 500
  workflows, five of them failing.
- ``findings`` — *alpha*'s *informational* band with 300 findings, the check's reading
  cap.

And mounted as the deployment that runs mounts its checks (backlog #91's note, §2,
2026-10-17), the wall it is mostly looked at on:

- ``deployed`` — *alpha*'s five checks at the root, each a card, beside the engine's
  own node, and nothing of *beta*'s. Every node of *alpha*'s keeps what it had beneath
  the team — its code, its lines word for word, its title, its *about*, its claim and
  its rank — so the cards are the team's boxes, mounted again.

The render harness shows the recorded tree as a page of the fixture sheet
(``ui_fixtures.py``, ``anonymized_tree``); ``test_wall_cost.py`` and
``test_wall_cost_browser.py`` measure what the wall costs on every variant
(``docs/testing-the-gui.md``, Modes 1 and 5).

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import StatusTree

#: The shapes: ``[path, code, [length, …]]`` per node a check wrote, containers implied.
SHAPES = Path(__file__).resolve().parent / "fixtures" / "anonymized_tree.json"

#: The deployment's ``reason_cap`` (§3.9); density, ``branch_cap`` and depth at their
#: defaults.
REASON_CAP = 30

VARIANTS = ("recorded", "outage", "blackout", "wide", "findings", "deployed")

#: Where the shapes made worse take their place, and the team whose checks the
#: deployed wall mounts at its root.
TEAM = "/alpha"
#: The recorded tree's teams.
_TEAMS = ("/alpha", "/beta")
WORKFLOW_RUNS = "/alpha/github/actions"
INFORMATIONAL = "/alpha/wiz/informational"
#: The wide branch: a hundred repositories of five workflows each, the first workflow
#: of five of them failing — four errors and a warning, as the prototype had it.
WIDE_REPOSITORIES = 100
WIDE_WORKFLOWS = ("ci.yml", "codeql.yml", "dependabot-updates", "pipeline.yml",
                  "release.yml")
WIDE_FAILURES = {7: StatusCode.ERROR, 23: StatusCode.ERROR, 41: StatusCode.WARN,
                 58: StatusCode.ERROR, 86: StatusCode.ERROR}
#: The band's lines made 300: the check reads up to 500 findings a run.
MANY_FINDINGS = 300
#: The one line a failing leaf gets where it had none.
A_LINE = 60

# --- what the shapes do not record ---------------------------------------------------

#: The levels' titles, as the deployment's `nodes.yaml` and its types label them.
_TITLES_BY_NAME = {
    "alpha": "Team alpha", "beta": "Team beta",
    "aws": "AWS accounts", "github": "GitHub repositories", "wiz": "Cloud security",
    "loadtest": "Loadtest analysis", "github-rate-limit": "GitHub API budget",
    "actions": "Workflow runs", "code_scanning_quality": "Code scanning, quality",
    "code_scanning_security": "Code scanning, security", "issues": "Open issues",
    "pull_requests": "Pull requests", "sbom_check": "Dependency graphs",
    "secret_scanning_alerts": "Secret scanning",
    "security_advisories": "Security advisories", "live": "The live account",
    "develop": "The development account", "infrastructure": "Shared plumbing",
    "nonlive": "The test account", "batch": "Batch job queues",
    "cloudwatch": "CloudWatch alarms", "ec2": "EC2 instances",
    "lambda": "Lambda functions", "codepipeline": "Pipelines",
}
#: A title stands on the teams, the checks and the checks' first levels; a repository,
#: a workflow, a function, a queue and a band carry their names alone.
_TITLED_DEPTHS = (1, 2, 3, 4)

#: An *about* on a team and on each of its checks, what the hover card reads.
_ABOUTS = {
    "": ("The team's checks: its AWS accounts, its GitHub repositories, its cloud "
         "security findings, its loadtests and its API budget."),
    "aws": ("The team's AWS accounts, read with a read-only role. Each account lists "
            "its services' rosters; costs and alarms are on the team dashboard."),
    "github": ("The team's repositories in the organisation, archived ones left out. "
               "Each aspect below lists the repositories it flags."),
    "wiz": ("The cloud security findings on the team's accounts, one band per "
            "severity. A band's lines are its open findings."),
    "loadtest": ("Every loadtest recorded in the last week, and whether its analysis "
                 "was written up. A warning is a run somebody has to go back to."),
    "github-rate-limit": ("What is left of the organisation token's two budgets, REST "
                          "and GraphQL. Every check that reads GitHub spends it."),
}

#: The checks, five to a team, each mounted at its node (ADR-0044): how often it
#: runs, and for the three whose node is their own, what it read and how it is
#: configured, as the facts block on its page shows them.
_CHECKS = ("aws", "github", "wiz", "loadtest", "github-rate-limit")
_FREQUENCY = 600
_WALL_SECONDS = 41.0
_REPORTS = {
    "github": ("Read **20 repositories** and 63 workflow runs in 41 s.\n\n"
               "- Rate limit: 4,812 of 5,000 requests left.\n"
               "- Two archived repositories skipped.\n"
               "- Dependabot: 14 open alerts read, 3 of them high.\n"
               "- Branch protection read on 20 default branches.\n"
               "- The next full read of the roster in an hour."),
    "loadtest": "The last test: 1,200 requests, p95 412 ms, no errors.",
    "github-rate-limit": "4,812 of 5,000 requests left; 4,864 of 5,000 points.",
}
_CONFIGS = {
    "github": ("- **scope:** org\n- **organisation:** example\n"
               "- **aspects:** actions, dependabot, branches\n"
               "- **frequency:** 10 minutes"),
    "loadtest": ("- **window:** 8 days\n- **expected:** at least 1 run\n"
                 "- **frequency:** 10 minutes"),
    "github-rate-limit": "- **budgets:** core, graphql\n- **frequency:** 10 minutes",
}

#: The lines that are members (ADR-0036): a roster's instances, a finding, an open
#: pull request, a repository without a dependency graph. Each takes a slug of its
#: node's name and its place, so a line's Copy chip has an address.
_MEMBER_NODES = re.compile(r"/(ec2|pull_requests|sbom_check)$|/wiz/[^/]+$")

#: The aws type's rosters worth reading when all is well (ADR-0063): the services'
#: nodes and every batch queue.
_SHOW_WHEN_QUIET = re.compile(
    r"^/[^/]+/aws/[^/]+/(ec2|lambda|codepipeline|batch)$|^/[^/]+/aws/[^/]+/batch/[^/]+$")

#: The severity bands' declared rank (ADR-0055), so a name sort does not file
#: *informational* between *high* and *low*.
_RANKS = {
    "critical": 1, "high": 2, "medium": 3, "low": 4, "informational": 5,
    "error": 1, "warning": 2, "note": 3,
}
_RANKED_PARENTS = re.compile(
    r"/(wiz|code_scanning_security|security_advisories|code_scanning_quality)$")

# --- made-up text of a recorded length -----------------------------------------------

#: What a line says, by the kind of node it stands on — the shape of each check's
#: line, in generic words — and then filler until the recorded length is reached.
_FILLER = ("the reading holds", "nothing changed since the morning",
           "the next read comes with the hour", "seen on the last three runs",
           "within its window", "the roster holds what it held yesterday",
           "no alarm stands against it", "read in full")
_FINDINGS = (
    "Resource running end-of-life software",
    "VM with kernel vulnerabilities running a container",
    "Operating system reaching end of life in the next 90 days",
    "Bucket without object-level write logging",
    "Unused role with administrative permissions",
    "Security group open to the internet on port 22",
    "Function on a deprecated runtime",
    "Volume without encryption at rest",
    "Access key not rotated in 365 days",
    "Container image with critical vulnerabilities",
    "Load balancer with an outdated TLS policy",
    "Snapshot shared publicly",
    "Instance profile with wildcard permissions",
    "Database without deletion protection",
    "Log group without a retention period",
    "Registry without image scanning",
    "Queue without encryption at rest",
)
_RESOURCES = ("vm", "container", "bucket", "function", "role", "volume", "image",
              "cluster", "database")


def _age(rng: random.Random) -> str:
    return (f"{rng.randrange(1, 20)}h {rng.randrange(1, 60)}m" if rng.random() < 0.5
            else f"{rng.randrange(1, 12)}d {rng.randrange(1, 24)}h")


def _head(path: str, index: int, failing: bool, rng: random.Random) -> str:
    """The line's own words, before any filler."""
    segments = path.split("/")[1:]
    name = segments[-1]
    if "/wiz/" in path:
        return f"{_FINDINGS[index % len(_FINDINGS)]} — "
    if re.search(r"/github/actions/[^/]+/[^/]+$", path):
        number = rng.randrange(100, 4100)
        verdict = (f"failed after {rng.randrange(1, 10)}m{rng.randrange(10, 60)}s"
                   if failing else "passed")
        return f"{segments[-2]} (main) / {name}: {verdict} (#{number})"
    if name == "pull_requests":
        return (f"#{4800 + index} waiting {rng.randrange(2, 30)}h for a reviewer, "
                f"{'past its day' if failing else 'within its day'}")
    if name == "sbom_check":
        return f"repository-{index + 1:02d}: no dependency graph (0 manifests)"
    if name == "github":
        return "20 repositories read, 2 archived left out"
    if name == "github-rate-limit":
        return ("core: 4979 of 5000 requests left, resets in 27 min" if index == 0
                else "graphql: 4864 of 5000 points left, resets in 17 min")
    if name == "loadtest":
        return ("only 0 loadtest runs in the last 8d — expected at least 1" if failing
                else "3 loadtest runs in the last 8d, each written up")
    if name == "ec2":
        return (f"instance-{index + 1:02d}: 1 ({_age(rng)})"
                + (" — older than the 30d its name allows" if failing else ""))
    if name == "cloudwatch":
        if failing:
            return f"{rng.randrange(1, 5)} alarms in ALARM, the first {_age(rng)} ago"
        return f"{rng.randrange(4, 34)} alarms with the team's tag, none in ALARM"
    if name == "batch":
        return ("a queue's last job failed" if failing
                else "every queue's last job succeeded within its window")
    if name == "lambda":
        return "scheduled functions are expected to run; silence means one did not"
    if name == "codepipeline":
        return "no pipeline failed in the last 24h"
    if "/lambda/" in path:
        if failing:
            return f"{name}: 1 error in the last 1h, {rng.randrange(2, 59)}m ago"
        return f"{name}: no errors in the last 1h, invoked {rng.randrange(2, 50)}m ago"
    if "/codepipeline/" in path or "/batch/" in path:
        verdict = "failed" if failing else "succeeded"
        return f"{name}: last run {verdict} {_age(rng)} ago"
    return f"{name}: {'the check could not read its source' if failing else 'read'}"


def line_text(path: str, index: int, length: int, code: StatusCode) -> str:
    """One line of ``length`` characters at most, the same on every build: what a
    line of that kind says, and filler to the recorded length — a finding fills with
    the resources it touches, every other line with a few words more; a word the
    cut would break is left off."""
    rng = random.Random(f"{path}#{index}")
    failing = code in (StatusCode.ERROR, StatusCode.WARN)
    text = _head(path, index, failing, rng)
    if "/wiz/" in path:
        while len(text) < length:
            text += f"{rng.choice(_RESOURCES)}-{rng.randrange(100, 1000)} (eu-1), "
    else:
        while len(text) < length:
            text += f"; {rng.choice(_FILLER)}"
    if len(text) > length:
        # at a word, and never inside a bracket
        text = re.sub(r"\s*\([^)]*$", "", text[:length].rsplit(" ", 1)[0])
    return text.rstrip(",;— ")


# --- the tree ------------------------------------------------------------------------


def shapes() -> list[tuple[str, StatusCode, list[int]]]:
    """The recorded shapes: each node a check wrote, with its code and its lines'
    lengths, in the file's order."""
    rows = json.loads(SHAPES.read_text(encoding="utf-8"))
    return [(path, StatusCode[code], list(lengths)) for path, code, lengths in rows]


def _is_leaf(path: str, paths: set[str]) -> bool:
    prefix = path + "/"
    return not any(other.startswith(prefix) for other in paths)


def _made_worse(rows: list[tuple[str, StatusCode, list[int]]],
                variant: str) -> list[tuple[str, StatusCode, list[int]]]:
    if variant == "recorded":
        return rows
    if variant == "outage":
        under = WORKFLOW_RUNS + "/"
        return [(path, StatusCode.ERROR if path.startswith(under)
                 and path.count("/") == WORKFLOW_RUNS.count("/") + 2 else code, lengths)
                for path, code, lengths in rows]
    if variant == "blackout":
        # every leaf of the two teams; the engine's own heartbeat keeps its word
        paths = {path for path, _code, _lengths in rows}
        return [(path, StatusCode.ERROR, lengths or [A_LINE])
                if _is_leaf(path, paths) and not path.startswith(HEARTBEAT_PATH)
                else (path, code, lengths)
                for path, code, lengths in rows]
    if variant == "wide":
        under = WORKFLOW_RUNS + "/"
        kept = [row for row in rows if not row[0].startswith(under)]
        for number in range(1, WIDE_REPOSITORIES + 1):
            repository = f"{WORKFLOW_RUNS}/alpha_repo-{number:03d}"
            kept.append((repository, StatusCode.OK, []))
            for place, workflow in enumerate(WIDE_WORKFLOWS):
                code = (WIDE_FAILURES.get(number, StatusCode.OK) if place == 0
                        else StatusCode.OK)
                kept.append((f"{repository}/{workflow}", code, [A_LINE]))
        return kept
    if variant == "findings":
        out = []
        for path, code, lengths in rows:
            if path == INFORMATIONAL:
                lengths = [lengths[i % len(lengths)] for i in range(MANY_FINDINGS)]
            out.append((path, code, lengths))
        return out
    raise ValueError(f"no variant {variant!r}; one of {', '.join(VARIANTS)}")


def _where_recorded(path: str) -> str | None:
    return path


def _where_deployed(path: str) -> str | None:
    """Where a recorded path stands on the deployed wall: :data:`TEAM`'s beneath the
    root, the engine's own node where it was, and a team itself and the other team's
    nowhere."""
    if path == TEAM or path.startswith(TEAM + "/"):
        return path[len(TEAM):] or None
    if any(path == team or path.startswith(team + "/") for team in _TEAMS):
        return None
    return path


def build(variant: str = "recorded", *,
          next_run_at: datetime | None = None) -> StatusTree:
    """The tree of ``variant`` (:data:`VARIANTS`), built the same way every time.
    ``next_run_at`` is the checks' armed next slot — a frequency from now unless the
    caller pins one, as the fixture sheet does to stay diffable.

    What a node is — its words, its title, its *about*, its claim, its rank, whether
    it is a check's own — is decided where it stands on the recorded tree, and written
    where it stands on ``variant``'s wall: the same place, but on the deployed wall."""
    rows = _made_worse(shapes(), "recorded" if variant == "deployed" else variant)
    where: Callable[[str], str | None] = (
        _where_deployed if variant == "deployed" else _where_recorded)
    if next_run_at is None:
        next_run_at = datetime.now(UTC) + timedelta(seconds=_FREQUENCY)
    tree = StatusTree()
    for recorded, code, lengths in rows:
        path = where(recorded)
        if path is None:
            continue
        name = recorded.rsplit("/", 1)[-1]
        lines = [line_text(recorded, i, length, code)
                 for i, length in enumerate(lengths)]
        members = bool(_MEMBER_NODES.search(recorded)) and bool(lines)
        reason: dict[str, str] | list[str] = (
            {f"{name}-{i + 1:03d}": text for i, text in enumerate(lines)}
            if members else lines)
        depth = recorded.count("/")
        tree.upsert(path, code, reason, members=members,
                    frequency_seconds=_FREQUENCY,
                    config=_CONFIGS.get(name) if depth == 2 else None,
                    report=_REPORTS.get(name) if depth == 2 else None,
                    show_when_quiet=True if _SHOW_WHEN_QUIET.match(recorded) else None)
    for recorded in sorted(_every_path(rows)):
        path = where(recorded)
        if path is None:
            continue
        segments = recorded.split("/")[1:]
        name = segments[-1]
        if len(segments) == 2 and name in _CHECKS:
            tree.set_check_mount(path)
            tree.set_run_facts(path, wall_seconds=_WALL_SECONDS,
                               next_run_at=next_run_at)
        if len(segments) in _TITLED_DEPTHS and name in _TITLES_BY_NAME:
            tree.set_title(path, _TITLES_BY_NAME[name])
        if len(segments) == 1 and name in ("alpha", "beta"):
            tree.set_about(path, _ABOUTS[""])
        elif len(segments) == 2 and name in _ABOUTS:
            tree.set_about(path, _ABOUTS[name])
        parent = recorded.rsplit("/", 1)[0]
        if _RANKED_PARENTS.search(parent) and name in _RANKS:
            tree.set_order(path, _RANKS[name])
    return tree


def _every_path(rows: list[tuple[str, StatusCode, list[int]]]) -> set[str]:
    """The paths the rows name and every container above them."""
    paths: set[str] = set()
    for path, _code, _lengths in rows:
        segments = path.split("/")[1:]
        for depth in range(1, len(segments) + 1):
            paths.add("/" + "/".join(segments[:depth]))
    return paths
