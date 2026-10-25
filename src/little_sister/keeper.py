"""The keeper seam: what carries ``var/state/`` somewhere durable (ADR-0071 §5).

The state layer is files (:mod:`~little_sister.state`), and files live on one
machine. An instance that is redeployed onto a fresh machine — the ordinary case
for the cloud deployment — comes up with an empty directory and loses the pins
somebody set and the history the log held. A **keeper** is the answer, and it is
deliberately the smallest possible one: a file store that mirrors the whole
directory without knowing what any file in it means.

Three methods, and no vocabulary of its own::

    load(name) -> bytes | None      # what the store holds for this file, or nothing
    save(name, data) -> None        # put these bytes there
    list() -> Sequence[str]         # every file the store holds

and five a keeper **may** answer, which the layer looks for by name and does without::

    tick(interval_seconds) -> bool  # once per interval, before any save: take saves?
    close() -> None                 # once, at graceful shutdown, after the last save
    changed_since_sync() -> Sequence[str]  # at a takeover: what the store changed
    push(name, data) -> None        # a save between two ticks: what an operator set
    standing_by() -> bool           # after the tick: does another instance stand by?

``tick`` is where a keeper does whatever it must do *every* interval whether or not
a file changed — a store that holds a lease on its prefix renews it here, and one
that is not the holder reads who is. Its answer says whether this interval's saves
are wanted at all: ``False`` and the layer sends nothing and keeps every file
marked as not yet taken, so the next ``True`` sends everything that changed
meanwhile. That is not a failure and is no line of the layer's — a keeper that
declines saves says why through its own self-report contributor (ADR-0072). A
``tick`` that *raises* is a failure, and is the layer's line. ``close`` is the
one signal a keeper gets that the process is ending on purpose, so a lease can be
given up rather than left to lapse; a process that is killed never sends it, which
every keeper must already survive.

``changed_since_sync`` is asked once, at the moment ``tick`` turns from *not taking
saves* to *taking them* — a standby became the holder, or a demoted holder took the
lease back — and answers the names of the files whose copy in the store differs from
what this instance last restored or last saved, by whatever token the store keeps
(S3's ETag, a version, a checksum); the library never sees the token. **Authority
follows the lease** (ADR-0077): whoever held it wrote the truth up to the moment it
lapsed, so every name answered is adopted — the local file set aside as ``.bak``, the
store's copy written in its place and loaded into the running process — before this
interval's first save, and a keeper that names nothing lets the new holder continue
with its own data, silently. A keeper without the method is the successor that
always continues, which is what every keeper did before the method existed; one
whose answer raises has failed its tick, and no save runs behind it that interval.

``push`` and ``standing_by`` are the keeper's **two cadences** (ADR-0134 decision
6). What an operator sets — a file the layer writes through, the pins — goes at the
next scheduler tick after it changes, as it goes to the disk the moment it does:
``push`` is a save between two of the keeper's ticks, which the keeper lands only
while it holds its store — a store with a lease puts it behind a heartbeat of its
own — and the layer asks it only while the keeper takes saves. What is observed —
the event log and the series — goes every ``keeper_interval`` while nobody stands
by, and every interval while anyone does: ``standing_by`` says which, as the keeper
last saw. A takeover, the stop's one save and the two flushes an action runs
between send everything at once — so a release a keeper offers as an action needs
nothing of its own to send what the process holds before its store is given up. A
keeper without ``push`` is handed the pins with the interval's saves, and one
without ``standing_by`` counts as always watched and is sent the observed state
every interval — both as every keeper was before the methods existed.

Bytes, not parsed state: a keeper carries `events.json.gz` and a package's sqlite
file with the same code, and a store that understood its cargo would have to be
released whenever the cargo's shape moved. **One keeper per instance**, registered in
the import-before-app slot beside the resolvers and under ADR-0064's rules — a name
claimed once, the registering package inferred and recorded, ``/system`` listing it.
A local installation registers none and loses nothing by it.

Two obligations an implementation carries, because the seam cannot enforce them:

* **Bound your client in seconds.** Saving runs on the scheduler tick, after the
  writer, and so does ``tick``; a client that waits on a socket for a minute is a
  minute of checks nobody ran. The layer catches what a keeper raises, but it
  cannot make a slow one fast.
* **Say it rather than merging it away.** Two instances against one bucket is not a
  case a keeper resolves by merging files; whatever it does instead — the S3 keeper
  holds a lease and puts the other instance in standby (little-sister-aws
  ADR-0004) — the operator needs to be told, and the self-report seam is where.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from little_sister.origins import calling_package
from little_sister.secrets import UNIDENTIFIED

#: A keeper's name is one identifier: it names the store in a log line, on
#: ``/system`` and in the two lines the heartbeat carries when it fails.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


@runtime_checkable
class Keeper(Protocol):
    """A file store that mirrors ``var/state/`` and never knows what it carries."""

    def load(self, name: str) -> bytes | None:
        """The bytes the store holds for state file ``name``, or ``None`` where it
        holds none. Raising says the store could not be reached, which is the
        failure the layer reports and starts without."""

    def save(self, name: str, data: bytes) -> None:
        """Put ``data`` there as ``name``. Raising is a failed save: the local file
        stands, and the layer says the copy is behind."""

    def list(self) -> Sequence[str]:
        """Every file name the store holds. Called once at startup, to decide what
        there is to restore."""


def takes_saves(keeper: Keeper, interval_seconds: float) -> bool:
    """Give the keeper its interval, and ask whether it takes this interval's saves.

    A keeper without ``tick`` takes every save, which is what every keeper did before
    the method existed. Whatever ``tick`` raises travels: the layer turns it into its
    line, and it is the layer's to catch.
    """
    tick = getattr(keeper, "tick", None)
    if tick is None:
        return True
    return bool(tick(interval_seconds))


def close_keeper(keeper: Keeper) -> None:
    """Tell the keeper the process is ending on purpose; nothing without ``close``."""
    close = getattr(keeper, "close", None)
    if close is not None:
        close()


def changed_since_sync(keeper: Keeper) -> list[str]:
    """Ask the keeper which files the store changed since this instance last
    synced with it — at a takeover, before the first save (ADR-0077).

    A keeper without ``changed_since_sync`` names nothing: the new holder continues
    with its own data, as every keeper's holder did before the method existed.
    Whatever the method raises travels, like ``tick``'s: the layer turns it into its
    line and takes no save that interval.
    """
    ask = getattr(keeper, "changed_since_sync", None)
    if ask is None:
        return []
    return [str(name) for name in ask()]


def push(keeper: Keeper, name: str, data: bytes) -> bool:
    """Hand the keeper one file between two of its ticks — what an operator set,
    at the next scheduler tick after it changed (ADR-0134 decision 6) — and say
    whether it took it there.

    A keeper without ``push`` takes nothing between its ticks, and the answer is
    ``False``: the file goes with the interval's saves, as every file did before
    the method existed. Whatever ``push`` raises travels; the layer turns it into
    its line, and the interval's saves send the file again.
    """
    method = getattr(keeper, "push", None)
    if method is None:
        return False
    method(name, data)
    return True


def standing_by(keeper: Keeper) -> bool:
    """Whether another instance stands by, as the keeper last saw — so the
    observed state goes every interval, and while nobody does every
    ``keeper_interval`` (ADR-0134 decision 6).

    A keeper without ``standing_by`` counts as always watched, and is sent the
    observed state every interval, as every keeper was before the method existed.
    Whatever it raises travels; the layer counts that as watched too, and says so.
    """
    ask = getattr(keeper, "standing_by", None)
    if ask is None:
        return True
    return bool(ask())


class KeeperConflictError(RuntimeError):
    """Two packages register a keeper, and neither said it meant to replace the
    other. Raised from :func:`register_keeper` — that is, from the application's
    import-before-app block, so the process does not start, the way a second claim
    on a secret scheme does not (ADR-0064)."""


@dataclass(frozen=True)
class Registration:
    """The instance's keeper: what answers, under which name, from which package."""

    name: str
    keeper: Keeper
    #: The package that registered it, inferred from the call site — ``""`` where
    #: the caller could not be identified.
    package: str
    #: The package this claim deliberately replaced, or ``""``.
    replaced: str = ""

    @property
    def owner(self) -> str:
        """The registering package as a page or a message should say it."""
        return self.package or UNIDENTIFIED


_keeper: Registration | None = None


def register_keeper(name: str, keeper: Keeper, *, replace: bool = False) -> None:
    """Register the instance's keeper under ``name`` (``s3``, ``nfs``, a test's).

    There is **one slot**, not one per name: a keeper mirrors the whole directory,
    so two of them would each carry a copy of what the other wrote and the last
    startup to run would decide which one the instance came back as. Re-registering
    from the *same* package replaces silently, because a registration module may be
    imported more than once and refusing that would refuse a reloading server; a
    claim from **another** package raises :class:`KeeperConflictError` naming both,
    and ``replace=True`` is how a replacement is made on purpose — recorded, and
    shown on ``/system`` rather than being indistinguishable from a first claim.
    """
    global _keeper
    if not _NAME.match(name):
        raise ValueError(
            f"a keeper name is one identifier (letters, digits, '_' and '-'), "
            f"not {name!r}")
    package = calling_package()
    replaced = ""
    if _keeper is not None:
        if _keeper.package == package:
            replaced = _keeper.replaced
        elif not replace:
            raise KeeperConflictError(
                f"two packages register a keeper: {_keeper.owner} registered "
                f"'{_keeper.name}' and {package or UNIDENTIFIED} claims the seam "
                f"too with '{name}'. An instance has one keeper, because two would "
                f"each carry a copy of what the other wrote and import order would "
                f"decide which one a restart came back as — install only one of "
                f"them, or pass replace=True where replacing the other is the "
                f"point (ADR-0071).")
        else:
            replaced = _keeper.package
    _keeper = Registration(name=name, keeper=keeper, package=package,
                           replaced=replaced)


def registered_keeper() -> Registration | None:
    """The instance's keeper, or ``None`` — which is a local installation, and a
    supported shape rather than a missing piece."""
    return _keeper


def forget_keeper() -> None:
    """Empty the slot (tests)."""
    global _keeper
    _keeper = None
