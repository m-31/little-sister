"""The hosts tree: a second deployment's wall, its names replaced.

``tests/fixtures/hosts_tree.json`` is a household's wall as its test instance drew it
on 2026-10-21 (backlog #91's note, §7.5) — for each node a check wrote its path, its
code and the lengths of its lines, the containers implied, in the shape of
``tests/fixtures/anonymized_tree.json``. Two cards: ``/computer``, nine hosts that the
library's own types write — ``host-metrics`` on each, ``macos-memory`` beside it on one
Mac, ``qnap-metrics`` beside it on the NAS — with a heartbeat file and a website among
them; and ``/system``, an ``aws`` check, a ``github`` check and its API budget. 101
nodes and 86 lines, most a host's five leaves of one short line each. It is the wall
the library's host types are measured on when they declare their big levels (the
note's §7.5, the third slice), as the anonymized tree is the wall of the family's
packages.

Every name that was the deployment's own has a generic one of the same length, so a
head and a chip stand as wide as they did; a level's own names — ``cpu``, ``disk``,
``ssh``, the services of ``aws`` — are the types' and stay. Every line is made-up text
of the recorded length in the shape its type writes, and every title and *about* the
deployment wrote is made-up text of its length too, so the wall's cost is measured on
the deployment's shape without a word of its own (R13). What the shapes do not record
is filled in as the deployment has it: the checks' mounts and how often each runs, the
titles and *abouts* its files and its ``nodes.yaml`` give, the ``aws`` rosters'
``show_when_quiet`` and their members — and what the packages and the library say of
their own nodes, each *about*'s first block by the length the hover card's map carried
and the count of the blocks after it, made-up text too. The library's host types say
what they declare today, read off :func:`checks`: an *about* and a handbook on each
aspect, the deployment's *about* winning where it wrote one, and neither on a
filesystem, a sensor, a drive or a watched process, whose card says what its run's
description does (ADR-0133).

**The library's host types** are built as the deployment's files configure them
(:func:`checks`), so the wall is drawn with the first look they propose
(:func:`first_looks`; ADR-0128): ``host-metrics`` on every host, ``macos-memory``
beside it on the Mac's node, which the two share, and ``qnap-metrics`` on the NAS.

The variant is :data:`VARIANT`, beside ``tests/anonymized_tree.py``'s; the wall cost's
files read both (``docs/testing-the-gui.md``, Modes 1 and 5).

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import json
import random
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from little_sister.checks import Check
from little_sister.checks.ssh import (
    HostMetricsCheck,
    MacosMemoryCheck,
    QnapMetricsCheck,
    host_metrics,
    macos_memory,
    qnap_metrics,
)
from little_sister.config import Config
from little_sister.first_look import FirstLooks
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests import family_looks

#: The shapes: ``[path, code, [length, …]]`` per node a check wrote, containers implied.
SHAPES = Path(__file__).resolve().parent / "fixtures" / "hosts_tree.json"

#: The deployment's ``reason_cap``, the library's default.
REASON_CAP = 6

#: The wall cost's name for this tree, beside the anonymized tree's variants.
VARIANT = "hosts"

# --- what the shapes do not record ---------------------------------------------------

#: Each check's mount and how often it runs, in seconds; one mount two checks share
#: (``host-metrics`` and ``macos-memory`` on the Mac that runs the heartbeat) once.
_MOUNTS = {
    "/computer/local/linux01": 120, "/computer/local/macbook": 120,
    "/computer/local/macmini/beacon": 180, "/computer/local/macmini/system": 120,
    "/computer/local/linux2": 120, "/computer/local/nas01/qnap": 300,
    "/computer/local/nas01/system": 300, "/computer/local/node2": 120,
    "/computer/local/router-gateway-1": 120, "/computer/remote/vps-01": 120,
    "/computer/remote/vps-01/website": 180, "/computer/remote/vps-02.lan": 120,
    "/system/aws": 300, "/system/github": 900, "/system/github-rate-limit": 180,
}
#: The ``host-metrics`` mounts: a host's five leaves are written beneath each.
HOST_METRICS = (
    "/computer/local/linux01", "/computer/local/macbook",
    "/computer/local/macmini/system", "/computer/local/linux2",
    "/computer/local/nas01/system", "/computer/local/node2",
    "/computer/local/router-gateway-1", "/computer/remote/vps-01",
    "/computer/remote/vps-02.lan")
_WALL_SECONDS = 2.0

#: The titles the deployment's files and its ``nodes.yaml`` give: a product's name, a
#: role, a long one written to try the ellipsis, the services' — none of them its own.
_TITLES = {
    "/computer/local/nas01": "Qnap NAS",
    "/computer/local/linux2":
        "A somewhat longer title that should lead to abbrivating ellipsis",
    "/computer/local/router-gateway-1": "Router",
    "/computer/remote/vps-01": "Remote Server",
    "/system/aws": "AWS",
    "/system/github": "GitHub — acme",
    "/system/github-rate-limit": "GitHub API budget — acme",
    "/little-sister": "Internal System Information",
}
#: The *abouts* the deployment wrote, by their length: made-up text here.
_ABOUT_LENGTHS = {
    "/computer/local/nas01": 36,
    "/computer/local/linux2": 65,
    "/computer/local/router-gateway-1": 29,
    "/computer/remote/vps-01": 77,
    "/computer/local/nas01/system/disk": 224,
    "/computer/local/nas01/system/load": 228,
    "/system/github": 149,
    "/system/github-rate-limit": 284,
}
#: What the packages and the library say of their own nodes, which the deployment did
#: not write: each *about*'s first block, by the length the hover card's map carried,
#: and how many blocks follow it — ``aws``'s aspects, ``github``'s and the library's
#: own branch.
_FIRST_BLOCKS = {
    "/system/aws/batch": (246, 4), "/system/aws/billing": (525, 5),
    "/system/aws/codepipeline": (171, 9), "/system/aws/ec2": (190, 10),
    "/system/aws/lambda": (452, 8), "/system/aws/s3": (517, 6),
    "/system/github/actions": (649, 2), "/system/github/issues": (331, 1),
    "/system/github/pull_requests": (203, 1),
    "/little-sister/aws-keeper": (145, 0), "/little-sister/engine": (280, 0),
    "/little-sister/readiness": (203, 0), "/little-sister/runtime": (196, 0),
    "/little-sister/security": (142, 0), "/little-sister/startup": (281, 0),
    "/little-sister/state": (321, 0),
}
#: The ``aws`` type's rosters worth reading when all is well (ADR-0063).
_SHOW_WHEN_QUIET = re.compile(r"^/system/aws/(ec2|lambda|codepipeline|batch|s3)$")
#: The lines that are members (ADR-0036): every ``aws`` line below the check's own,
#: and the API budget's two windows.
_MEMBER_NODES = re.compile(r"^/system/aws/.+|^/system/github-rate-limit$")

#: The processes the Mac's ``macos-memory`` watches, by the names their nodes have:
#: what makes ``processes`` its own beneath the node it shares (ADR-0015).
_WATCHED = ("syncer", "syncer-pull", "system-events")

#: Each host's name in its ``ssh`` line, its system and its processors.
_SYSTEMS = {"macbook": ("Darwin", 12), "macmini": ("Darwin", 8), "nas01": ("Linux", 1),
            "vps-01": ("Linux", 1), "vps-02.lan": ("Linux", 1)}

# --- made-up text of a recorded length -----------------------------------------------

_FILLER = ("as read", "within its level", "the reading holds", "read in full",
           "nothing changed since the last run", "as the last run had it")
_WORDS = ("the", "host", "reads", "its", "own", "figures", "over", "a", "connection",
          "each", "run", "and", "says", "what", "it", "found", "beside", "level",
          "where", "this", "node", "stands", "kept", "for", "team", "who", "answers")


def _host(path: str) -> str:
    """The host a path stands on: the segment beneath ``local`` or ``remote``."""
    segments = path.split("/")
    return segments[3] if len(segments) > 3 else ""


def _head(path: str, index: int, failing: bool, rng: random.Random) -> str:
    """The line's own words, in the shape its type writes them, before any filler."""
    name = path.rsplit("/", 1)[-1]
    parent = path.rsplit("/", 2)[-2]
    host = _host(path)
    if name == "cpu":
        return f"{rng.randrange(0, 40)}% busy"
    if name == "disk" or parent == "disk":
        used = rng.randrange(2, 92)
        total = rng.uniform(20, 950)
        mount = (f"/share/{name}" if parent == "disk" and name.isupper()
                 else f"/share/external/{name}" if parent == "disk"
                 else "/System/Volumes/Data" if _SYSTEMS.get(host, ("",))[0] == "Darwin"
                 else "/")
        return (f"{used}% used — {total * (100 - used) / 100:.1f} GiB free of "
                f"{total:.1f} GiB on {mount}")
    if name == "load":
        cores = _SYSTEMS.get(host, ("Linux", 4))[1]
        per = rng.uniform(0, 1.2)
        return f"{per:.2f} per core — load1 {per * cores:.2f} over {cores} CPUs"
    if name == "memory":
        used, total = rng.randrange(15, 80), rng.uniform(0.5, 32)
        return f"{used}% used — {total * used / 100:.1f} GiB of {total:.1f} GiB"
    if name == "ssh":
        system, cores = _SYSTEMS.get(host, ("Linux", 4))
        return (f"{host} reachable — {system}, {cores} CPUs, up "
                f"{rng.randrange(1, 700)}d {rng.randrange(0, 24)}h")
    if name == "compressor":
        share = rng.randrange(5, 40)
        return f"{share}% compressed — {8 * share / 100:.1f} GiB of 8.0 GiB RAM"
    if name == "pressure":
        return f"normal — {rng.randrange(20, 60)}% of memory free system-wide"
    if name == "swap":
        return f"{rng.randrange(100, 900)}.0 MiB used of 1.0 GiB allocated"
    if parent == "processes":
        return (f"{rng.randrange(10, 500)}.{rng.randrange(0, 10)} MiB RSS over "
                f"{rng.randrange(1, 4)} processes, oldest up {rng.randrange(1, 50)}d "
                f"{rng.randrange(0, 24)}h")
    if parent == "smart":
        return "GOOD"
    if parent == "temperature":
        return f"{rng.randrange(30, 50)} °C"
    if name == "website":
        return f"HTTP 200 in {rng.randrange(20, 99)} ms"
    if name == "beacon":
        return (f"stale: last changed {rng.randrange(10, 99)}d {rng.randrange(1, 24)}h "
                f"ago (max 20m)" if failing else "fresh: last changed 1m ago")
    if path == "/system/aws":
        return "1 account, 1 account/region pair in scope"
    if parent == "aws":
        if name == "billing":
            return (f"October so far: {rng.uniform(1, 9):.2f} USD · yesterday "
                    f"{rng.uniform(0, 1):.2f} USD")
        counted = {"lambda": "1 function", "s3": "3 buckets"}.get(name)
        thing = {"batch": "job queues", "codepipeline": "pipelines",
                 "ec2": "instances"}.get(name, name)
        return f"{counted or 'no ' + thing} in scope (eu-central-1)"
    if parent == "lambda":
        return (f"{name}: no errors, last run {rng.randrange(1, 20)}h "
                f"{rng.randrange(1, 60)}m ago · log: REPORT")
    if parent == "s3":
        return (f"{name}: {rng.uniform(1, 30):.1f} MB in {rng.randrange(2, 600)} "
                f"objects · +{rng.uniform(0, 4):.1f} MB since the day before")
    if path == "/system/github":
        return "58 repositories in scope"
    if name == "github-rate-limit":
        return ("core: 4941 of 5000 requests left, resets in 30min; 59 of it this "
                "process's own — the tightest of 2 windows GitHub keeps for this "
                "token; the other has 5000 left, resets in 45min" if index == 0
                else "graphql: 5000 of 5000 points left, resets in 59min — as "
                     "/rate_limit reports it; nothing here has spent it")
    if name == "aws-keeper":
        return ("standing by: another instance holds the keeper's lease, so this one "
                "reads the store and writes nothing to it until the lease is free")
    if name == "startup":
        return (f"checks/host-{index + 1:02d}.yaml: the about of a node runs past 400 "
                "characters, and a node's page shows it open beneath its name")
    return f"{name}: read"


def line_text(path: str, index: int, length: int, code: StatusCode) -> str:
    """One line of ``length`` characters at most, the same on every build: the line
    in its type's shape, and filler to the recorded length; a word the cut would break
    is left off, and a line shorter than its own words is cut where it must."""
    rng = random.Random(f"{path}#{index}")
    failing = code in (StatusCode.ERROR, StatusCode.WARN)
    text = _head(path, index, failing, rng)
    while len(text) < length:
        text += f"; {rng.choice(_FILLER)}"
    if len(text) > length:
        cut = text[:length]
        text = cut.rsplit(" ", 1)[0] if " " in cut and len(cut.rsplit(" ", 1)[0]) > 0 \
            else cut
    return text.rstrip(",;— ")


def _prose(path: str, length: int) -> str:
    """Made-up prose of exactly ``length`` characters, its last a full stop, for an
    *about* the deployment wrote."""
    rng = random.Random(f"{path}#about")
    text = "The"
    while len(text) < length:
        text += f" {rng.choice(_WORDS)}"
    cut = text[:length - 1]
    if cut.endswith(" "):
        cut = cut[:-1] + "a"  # a word of its own, never a space before the stop
    return cut + "."


# --- the tree ------------------------------------------------------------------------


def shapes() -> list[tuple[str, StatusCode, list[int]]]:
    """The recorded shapes: each node a check wrote, with its code and its lines'
    lengths, in the file's order."""
    rows = json.loads(SHAPES.read_text(encoding="utf-8"))
    return [(path, StatusCode[code], list(lengths)) for path, code, lengths in rows]


def _description(path: str) -> str:
    """What a host type's run says a node beneath one of its aspects reads — a
    filesystem, a sensor, a drive, a watched process — which the node's card shows,
    since it has no *about* (ADR-0133 decision 2); ``""`` for any other node, whose
    *about*, where it has one, its card shows instead."""
    if not any(path.startswith(mount + "/") for mount in _MOUNTS):
        return ""
    parent, name = path.rsplit("/", 2)[-2:]
    bay = name.removeprefix("drive")
    if parent == "disk":
        return host_metrics.VOLUME_DESCRIPTION
    if parent == "temperature":
        return {"system": qnap_metrics.SYSTEM_TEMPERATURE_DESCRIPTION,
                "cpu": qnap_metrics.CPU_TEMPERATURE_DESCRIPTION}.get(
            name, qnap_metrics.DRIVE_TEMPERATURE_DESCRIPTION.format(bay=bay))
    if parent == "smart":
        return qnap_metrics.DRIVE_SMART_DESCRIPTION.format(bay=bay)
    if parent == "processes":
        return macos_memory.PROCESS_DESCRIPTION
    return ""


def _frequency(path: str) -> int:
    """How often the check that writes ``path`` runs: its mount's, the deepest at or
    above it."""
    best = ""
    for mount in _MOUNTS:
        if (path == mount or path.startswith(mount + "/")) and len(mount) > len(best):
            best = mount
    return _MOUNTS.get(best, 120)


def checks() -> tuple[Check, ...]:
    """The library's host types at the deployment's mounts, the Mac's watching its
    processes: what proposes how their levels first look (ADR-0128). Nothing else of
    their files bears on it; nothing is read from a configuration's directory, and
    nothing runs."""
    nowhere = Path("/nonexistent")
    found: list[Check] = [
        HostMetricsCheck.from_config(
            {"type": "host-metrics", "path": mount, "host": _host(mount)}, nowhere)
        for mount in HOST_METRICS]
    found.append(QnapMetricsCheck.from_config(
        {"type": "qnap-metrics", "path": "/computer/local/nas01/qnap",
         "host": "nas01"}, nowhere))
    found.append(MacosMemoryCheck.from_config(
        {"type": "macos-memory", "path": "/computer/local/macmini/system",
         "host": "macmini",
         "processes": [{"name": name, "pattern": name} for name in _WATCHED]},
        nowhere))
    return tuple(found)


def first_looks(tree: StatusTree, config: Config) -> FirstLooks:
    """The first look the hosts wall is drawn with: what the library's host types
    propose (:func:`checks`), and the family's packages for the aws and github checks
    beside them — the aws check standing for its one account — stated by path, since
    they are not installed here (``family_looks``), under ``config``; the deployment's
    ``nodes.yaml`` says nothing of it."""
    return FirstLooks(checks(), family_looks.declared(tree, account_node=False), config,
                      tree.named_by_run)


def build(variant: str = VARIANT, *, next_run_at: datetime | None = None) -> StatusTree:
    """The hosts tree, built the same way every time. ``next_run_at`` is the checks'
    armed next slot — two minutes from now unless the caller pins one."""
    if variant != VARIANT:
        raise ValueError(f"no variant {variant!r}; the hosts tree is {VARIANT!r}")
    if next_run_at is None:
        next_run_at = datetime.now(UTC) + timedelta(seconds=120)
    tree = StatusTree()
    for path, code, lengths in shapes():
        lines = [line_text(path, i, length, code) for i, length in enumerate(lengths)]
        name = path.rsplit("/", 1)[-1]
        members = bool(_MEMBER_NODES.search(path)) and bool(lines)
        reason: dict[str, str] | list[str] = (
            {f"{name}-{i + 1:03d}": text for i, text in enumerate(lines)}
            if members else lines)
        tree.upsert(path, code, reason, members=members,
                    description=_description(path),
                    frequency_seconds=_frequency(path),
                    show_when_quiet=True if _SHOW_WHEN_QUIET.match(path) else None)
    for mount in _MOUNTS:
        tree.set_check_mount(mount)
        tree.set_run_facts(mount, wall_seconds=_WALL_SECONDS, next_run_at=next_run_at)
    for path, title in _TITLES.items():
        tree.set_title(path, title)
    for path, length in _ABOUT_LENGTHS.items():
        tree.set_about(path, _prose(path, length))
    for path, (length, after) in _FIRST_BLOCKS.items():
        blocks = [_prose(path, length)]
        blocks += [_prose(f"{path}#{block}", 40) for block in range(after)]
        tree.set_about(path, "\n\n".join(blocks))
    # what each host type declares for its aspects, the deployment's about winning
    # where it wrote one; a node a run names beneath an aspect takes none of it
    for check in checks():
        for name, labels in check.subnode_labels.items():
            path = f"{check.path}/{name}"
            if tree.snapshot(path) is None:
                continue
            if path not in _ABOUT_LENGTHS and labels.get("about"):
                tree.set_about(path, labels["about"])
            if labels.get("handbook"):
                tree.set_handbook(path, labels["handbook"])
    return tree
