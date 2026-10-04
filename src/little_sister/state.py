"""The state layer: what a restart keeps, as files under ``var/state/`` (ADR-0071).

Three layers hold what this process wants to survive a restart. **Memory** is
where the application works (ADR-0001/0002). **This layer** is memory serialized
to JSON files under ``var/state/`` and read back at startup, so an instance
initializes with what it had — the maintenance pins, the event log, the series,
and whatever joins them later. **Packages** sit behind two seams outside it: a
store that speaks to a service per record, and a :mod:`~little_sister.keeper` — a
file store such as S3 that loads every file here at startup and saves copies
periodically without knowing what any of them means. Nothing that is a service
enters the core.

Two write disciplines, one atomic write. A file is **written through** by the
code that owns it — a pin is written when it changes, so a crash a minute later
loses nothing — through :meth:`StateLayer.write`. A file is **kept** when its
state changes too often for that: :meth:`StateLayer.keep` registers a producer,
and the scheduler tick writes every kept file at most once per interval
(``state_interval`` in ``settings.yaml``) and once more at graceful shutdown; an
unclean shutdown loses at most the interval. Every write is a temporary file in
the same directory and :func:`os.replace`, the discipline the maintenance file
always had, so a reader never sees half a file.

**A failure never refuses to start, and is never silent.** A file that cannot be
read starts that state empty and is reported for the life of the process — what
somebody set before the restart is not in force, and a restart is the one thing
that could change that. A write that fails keeps the state in memory and is
reported until the next write succeeds — nothing is lost yet; the next restart is.
Both are lines on ``/little-sister``, through the self-report seam
(:mod:`~little_sister.self_report`), which is why :meth:`StateLayer.lines` exists.

**Authority follows the lease** (ADR-0077). Where a keeper holds a lease on its
store, whoever held it wrote the truth up to the moment it lapsed, and an instance
that stood by meanwhile holds a shadow of the store, never its competitor. So a
state file has a second direction: a ``restore`` callable, registered beside the
producer of a kept file (:meth:`StateLayer.keep`) or on its own for a file written
through (:meth:`StateLayer.restore_with`), that takes the parsed payload and
replaces what the running process holds. The moment is the keeper's ``tick``
turning from *not taking saves* to *taking them*: the layer asks the keeper which
files the store changed since this instance last synced with it and **adopts**
every one — the running process first, then the local file set aside as
``<name>.bak`` and the store's copy written in its place — before the interval's
first save. A file whose adoption failed is **held out of the mirror** until one
lands — the instance holds the lease now and the interval's saves run, and a save
of that file would put its shadow over the authoritative copy — and is retried
every interval. The ``.bak`` is the one copy kept, this machine's own and never
mirrored; the ``state`` child lists it beside the live copy and *take the backups*
swaps them back through the same adoption.

The files are JSON because they are machine-written and machine-read; YAML stays
for what a person authors. Nothing else loose in ``var/`` is state: logs, pids
and TLS material stay where they are.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from little_sister.codes import StatusCode
from little_sister.keeper import (
    Keeper,
    changed_since_sync,
    close_keeper,
    registered_keeper,
    takes_saves,
)
from little_sister.logger import logger
from little_sister.reasons import Entry
from little_sister.spans import coarse_span

if TYPE_CHECKING:
    from little_sister.lease import Lease

#: Fixed runtime path, relative to the working directory a deployment is started
#: from (ADR-0020) and git-ignored; not env-overridable, like the maintenance file
#: before it (ADR-0014).
STATE_DIR = "var/state"

#: How often the kept files are written, in seconds, unless ``settings.yaml``
#: says otherwise.
DEFAULT_STATE_INTERVAL = 60

#: The maintenance side-table (ADR-0014), written through by the tree.
MAINTENANCE_FILE = "maintenance.json"

#: The event log (ADR-0001), kept periodically; node history is derived from it.
EVENTS_FILE = "events.json"

#: The series (ADR-0087), kept periodically: every subject's kept readings, so a
#: restarted instance shows yesterday's records and a keeper carries them with
#: the rest.
SERIES_FILE = "series.json"

#: What a half-written file is called while it is being written. Excluded from the
#: mirror a keeper carries: what is not yet a state file is not state.
TEMP_SUFFIX = ".tmp"

#: What a file set aside by an adoption is called — the one copy the layer keeps of
#: what it replaced (ADR-0077). Local like ``.tmp`` and excluded from the mirror the
#: same way: it is this machine's shadow of the store, not the store's state, and a
#: keeper that carried it would hand it to the next instance as a state file.
BACKUP_SUFFIX = ".bak"

#: The other direction of a state file: takes the parsed payload and replaces what
#: the running process holds — under the process's own lock, and never inside it for
#: longer than the swap. Raising is a failed adoption of that file, reported and
#: never propagated.
Restore = Callable[[Any], None]


@dataclass
class _Registered:
    """What the layer knows about one file beyond its name: the producer of a
    kept file, the ``restore`` of a file the process can take in at runtime, or
    both — a written-through file registers only the latter."""
    producer: Callable[[], object] | None = None
    restore: Restore | None = None
    #: The digest of what the periodic write last wrote — or of the copy an
    #: adoption put in its place — so an unchanged state is not rewritten every
    #: interval: a file that did not change is not a file to touch. The digest and
    #: never the text, which for the series is megabytes the process would hold
    #: for its whole life only to compare them with the next text.
    written: str | None = None


@dataclass
class _Outcome:
    #: Why the file could not be read at startup; stands for the process lifetime.
    load_error: str = ""
    #: Why the last write failed; cleared by the next write that succeeds.
    save_error: str = ""
    #: Why the last save of this file **to the keeper** failed; cleared the same
    #: way, by the next save of it that lands there.
    keeper_error: str = ""
    #: The digest of what the keeper last took, so an unchanged file is not sent
    #: again every interval — seeded by a restore and by an adoption from the
    #: store, since what arrived from there is what it holds.
    keeper_saved: str = ""
    #: The ``load.<name>`` line an adoption left standing, and its code (ADR-0077):
    #: ERROR for a copy the process could not take in, WARN for one written to disk
    #: with nothing in the process registered to take it. Text rather than a detail,
    #: because the verb is the adoption's own; cleared by the next adoption of the
    #: file that succeeds.
    adopted: str = ""
    adopted_code: StatusCode = StatusCode.ERROR
    #: Whether the file is held out of the mirror: its adoption from the store
    #: failed, so what is on disk is this instance's shadow and a save of it would
    #: overwrite the authoritative copy. Retried every interval; lifted by the
    #: adoption that lands, or by a store that no longer holds the file.
    held: bool = False


class StateLayer:
    """The directory of state files, the two write disciplines, and what each
    file's last load and save came to."""

    def __init__(self, directory: str | Path = STATE_DIR, *,
                 interval_seconds: int = DEFAULT_STATE_INTERVAL,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._directory = Path(directory)
        self._interval = max(1, int(interval_seconds))
        self._clock = clock
        # The wall clock stamps a file when it is written, and a file's own mtime
        # is the same clock: the report says how old a backup and its live copy
        # are from these stamps alone, both local, one clock (ADR-0077).
        self._wall = wall
        # Guards the ledger, the file table and the stamps, which the scheduler
        # thread, the web threads (a pin written through, a button pressed) and
        # the shutdown flush share.
        self._lock = threading.Lock()
        # Serializes the two things that replace files wholesale — the flush, which
        # may adopt at a takeover, and *take the backups* from a web thread — so
        # neither renames a file the other is halfway through writing. Held around
        # the keeper's tick and saves too, which is why it is not ``_lock``: a
        # bounded client may still take seconds, and a pin written through must
        # not wait on it.
        self._swap_lock = threading.Lock()
        self._files: dict[str, _Registered] = {}
        self._outcomes: dict[str, _Outcome] = {}
        #: When each file in the directory — a live one or a ``.bak`` — was last
        #: written, on the wall clock: recorded by every write this layer makes
        #: and read once from the disk at startup (:meth:`take_stock`), so the
        #: report never has to look.
        self._stamps: dict[str, float] = {}
        self._last_flush: float | None = None
        # Whether the keeper took this interval's saves — the flip from ``False``
        # to ``True`` is the takeover the adoption waits on (ADR-0077). Starts as
        # not taking: the first interval a keeper takes is a takeover too, and a
        # keeper that names nothing makes it a silent one.
        self._taking = False
        # The keeper's own two records (§5): why the load failed, which stands for
        # the life of the process, and the name of the keeper that answered — kept
        # beside it so a line can say which store it is talking about even after
        # the registration is gone.
        self._keeper_load_error = ""
        self._keeper_name = ""
        #: Why the keeper's last ``tick`` raised; cleared by the next one that
        #: returns. A tick that *declines* is not this — it is the keeper's own line.
        self._keeper_tick_error = ""
        #: The directory's lease, once the server's start has taken it (ADR-0090):
        #: asked before every write, and let go after the stop's one save.
        self._lease: Lease | None = None
        #: Set by the stop's one save (ADR-0088 decision 3): nothing writes the
        #: directory after it.
        self._closed = False

    @property
    def directory(self) -> Path:
        return self._directory

    def hold(self, lease: Lease) -> None:
        """Write under ``lease`` from now on: every write asks it first, and a layer
        whose lease was taken writes nothing more (ADR-0090 decision 7). The stop
        releases it after its one save."""
        self._lease = lease

    @property
    def lost(self) -> str | None:
        """Who holds the directory now, once the lease this layer writes under was
        taken from it (ADR-0090 decision 7) — the engine asks on every tick, and
        runs no more checks from then on. ``None`` while the lease is its own, and
        for a layer that holds none."""
        return self._lease.lost if self._lease is not None else None

    def _may_write(self) -> bool:
        """Whether this layer may still write the directory: not after the stop's
        one save, and not once the lease it holds is no longer its own."""
        if self._closed:
            return False
        return self._lease is None or self._lease.still_ours()

    def path(self, name: str) -> Path:
        """Where state file ``name`` lives."""
        return self._directory / name

    # --- reading ---

    def read(self, name: str) -> Any:
        """The parsed JSON of state file ``name``.

        ``None`` when there is no file — a first start, or a state never written
        — and also when the file cannot be read or is not JSON, which is a **load
        failure**: recorded, logged, and a line on the heartbeat for as long as the
        process runs. The caller starts that state empty either way; it never
        refuses to start over a file (ADR-0071).
        """
        path = self.path(name)
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            # json.JSONDecodeError and a bad encoding are both ValueErrors.
            self.report_load_failure(name, str(error))
            return None

    def report_load_failure(self, name: str, detail: str) -> None:
        """Record that ``name`` could not be loaded at startup — called by
        :meth:`read`, and by a reader that found a file it cannot use (an older
        shape is warned about and rewritten by the next save, never migrated;
        ADR-0014)."""
        with self._lock:
            self._outcome(name).load_error = detail
        logger.error("state: %s could not be loaded at startup: %s; starting "
                     "without it", self.path(name), detail)

    # --- writing ---

    def write(self, name: str, payload: object) -> bool:
        """Write ``payload`` as state file ``name`` now — the write-through
        discipline — atomically. A failure is logged and recorded, never raised:
        the state stays in memory for the session, and the heartbeat says the
        file is behind until a later write succeeds. After the stop, or once the
        lease is lost, nothing is written and the answer is ``False``."""
        if not self._may_write():
            return False
        return self._write_text(name, _dumps(payload))

    def keep(self, name: str, producer: Callable[[], object], *,
             restore: Restore | None = None) -> None:
        """Register a **kept** file: ``producer`` returns its JSON-serializable
        state and is called on the scheduler tick, so it copies under its own
        lock and returns — never inside the tree's lock for longer than the copy
        takes. The file is written by :meth:`tick` at most once per interval, and
        by :meth:`flush` at shutdown, only when the state changed.

        ``restore`` is the other direction (ADR-0077): given the parsed payload of
        a copy adopted at runtime — the store's at a takeover, the backup's on
        the way back — it replaces what the process holds, under the process's own
        lock and never inside it for longer than the swap. A kept file without
        one is adopted on disk only, and its line says so. Files are adopted in
        registration order, so register the one whose adoption the others write
        into first — the event log before the pins.
        """
        with self._lock:
            registered = self._files.setdefault(name, _Registered())
            registered.producer = producer
            registered.written = None
            if restore is not None:
                registered.restore = restore

    def restore_with(self, name: str, restore: Restore) -> None:
        """Register the other direction of a file the process **writes through**
        (ADR-0077) — the maintenance side-table, whose producer is the write
        itself: ``restore`` takes the parsed payload of an adopted copy and
        replaces what the process holds. The same callable :meth:`keep` takes,
        for a file that has no producer to register beside it."""
        with self._lock:
            self._files.setdefault(name, _Registered()).restore = restore

    def tick(self) -> bool:
        """The scheduler's call, once per tick: write the kept files when an
        interval has passed since the last time, and say whether this tick ran
        that save — the engine's tick line says so (ADR-0095 decision 5). The first
        tick only starts the interval — there is nothing to write yet that startup
        did not just read."""
        now = self._clock()
        with self._lock:
            if self._last_flush is None:
                self._last_flush = now
                return False
            if now - self._last_flush < self._interval:
                return False
            self._last_flush = now
        return self.flush()

    def flush(self) -> bool:
        """Write every kept file whose state changed since its last write — the
        periodic write, and the one at graceful shutdown. A producer that raises is
        a failed save of its file, reported like any other, and the rest are still
        written. Then the keeper: its tick, the adoption where that tick is a
        takeover (ADR-0077), and the saves it takes. ``False`` where the layer may
        no longer write and nothing ran."""
        with self._swap_lock:
            if not self._may_write():
                return False
            self._flush()
            return True

    def _flush(self) -> None:
        # Call only while holding the swap lock.
        with self._lock:
            kept = [(name, item) for name, item in self._files.items()
                    if item.producer is not None]
        for name, item in kept:
            assert item.producer is not None
            try:
                text = _dumps(item.producer())
            except Exception as error:
                logger.exception("state: the producer of %s raised", name)
                with self._lock:
                    self._outcome(name).save_error = (
                        f"its producer raised: {error!r}")
                continue
            data = text.encode("utf-8")
            digest = _digest(data)
            if digest == item.written:
                continue
            if self._write_bytes(name, data):
                item.written = digest
        # The keeper, after the writer and on the same interval (ADR-0071 §5), so
        # what it takes is what this tick just wrote rather than the tick before —
        # and only when its tick says so: a keeper that is not the holder of its
        # store this interval takes nothing, and nothing here counts that as a save.
        wanted = self._tick_keeper()
        if wanted and not self._taking:
            # The flip — a standby became the holder, or a demoted holder took
            # the lease back: whoever held it wrote the truth meanwhile, so what
            # the store changed is adopted before this interval's first save
            # (ADR-0077). An ask that fails takes no save behind it, and is asked
            # again next interval.
            wanted = self._adopt_from_keeper()
        elif wanted:
            self._retry_held()
        if wanted:
            self._save_to_keeper()
        self._taking = wanted

    def shutdown(self) -> None:
        """The graceful end — the stop's one save (ADR-0088 decision 3): the last
        flush, then the keeper's ``close``, after the last save so what a lease
        covered has landed before it is given up; then the layer closes, so that
        nothing writes the directory after it, and the directory's lease is let go
        (ADR-0090). A process that is killed does none of it, which is the case
        every keeper and the lease survive on their own. A second call does
        nothing."""
        if self._closed:
            return
        self.flush()
        registration = registered_keeper()
        if registration is not None:
            try:
                close_keeper(registration.keeper)
            except Exception:
                logger.exception("state: the %s keeper failed to close",
                                 registration.name)
        with self._swap_lock:
            self._closed = True
        if self._lease is not None:
            self._lease.release()

    def _tick_keeper(self) -> bool:
        """Give the keeper its interval and ask whether it takes saves now.

        Whatever ``tick`` raises is recorded and is a WARN line until a tick
        returns — the same standing as a failed save, and for the same reason:
        nothing is lost yet, the copy is behind. A keeper that raises here takes no
        saves this interval, since a save behind a failed tick is exactly what the
        method exists to prevent.
        """
        registration = registered_keeper()
        if registration is None:
            return False
        self._keeper_name = registration.name
        try:
            wanted = takes_saves(registration.keeper, self._interval)
        except Exception as error:
            with self._lock:
                self._keeper_tick_error = repr(error)
            logger.warning("state: the %s keeper's tick failed: %r; no save this "
                           "interval", registration.name, error)
            return False
        with self._lock:
            self._keeper_tick_error = ""
        return wanted

    def _atomic_write(self, name: str, data: bytes) -> None:
        """The one write: a temporary file in the same directory and
        :func:`os.replace`, so a reader sees the old file whole or the new one
        whole. Raises :class:`OSError`; what a failure *means* is the caller's —
        a local save that fell behind, or a restore that could not be put in
        place."""
        path = self.path(name)
        tmp = path.with_name(path.name + TEMP_SUFFIX)
        self._directory.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
        with self._lock:
            self._stamps[name] = self._wall()

    def _write_text(self, name: str, text: str) -> bool:
        return self._write_bytes(name, text.encode("utf-8"))

    def _write_bytes(self, name: str, data: bytes) -> bool:
        path = self.path(name)
        try:
            self._atomic_write(name, data)
        except OSError as error:
            with self._lock:
                self._outcome(name).save_error = str(error)
            logger.warning("state: cannot write %s: %s; keeping it in memory",
                           path, error)
            return False
        with self._lock:
            self._outcome(name).save_error = ""
        return True

    # --- the keeper ---

    def restore_from_keeper(self) -> None:
        """Fetch what the instance's keeper holds into this directory, **before**
        anything reads it (ADR-0071 §5).

        The one ordering that matters: a keeper loads first, and then the files are
        read as they are, so an instance started on a fresh machine comes up as the
        one that stopped on the old one. What the keeper holds therefore **wins**
        over a local file of the same name — which is the point on a new machine,
        and on an old one is only reachable if a previous save to the keeper failed,
        where the WARN line below has been standing ever since.

        **A failure never refuses to start.** A keeper that cannot be reached — no
        network, no credential, a bucket that is not there — leaves every local file
        exactly as it is, and the instance starts with them; the failure is one
        ERROR line for as long as the process runs. Per file, too: one name that
        cannot be fetched leaves that file alone and the others still arrive.
        """
        registration = registered_keeper()
        if registration is None:
            return
        keeper = registration.keeper
        self._keeper_name = registration.name
        try:
            names = list(keeper.list())
        except Exception as error:
            self._report_keeper_load_failure(f"listing what it holds failed: "
                                             f"{error!r}")
            return
        restored = []
        for name in names:
            if not _is_plain_name(name):
                # The name is a path component here, and it came from somewhere
                # else: a store answering `../config/users.yaml` must not be able
                # to write outside the directory it is mirroring.
                self._report_keeper_load_failure(
                    f"it offered {name!r}, which is not a state file name")
                continue
            try:
                data = keeper.load(name)
            except Exception as error:
                self._report_keeper_load_failure(f"{name}: {error!r}")
                continue
            if data is None:
                # Listed and then gone, or a store that lists more than it holds.
                # Nothing was promised about this file, so nothing is claimed.
                logger.info("state: the %s keeper holds nothing for %s",
                            registration.name, name)
                continue
            try:
                self._atomic_write(name, data)
            except OSError as error:
                self._report_keeper_load_failure(f"{name} could not be written "
                                                 f"here: {error}")
                continue
            # What arrived from the keeper is what it holds: the first flush
            # after a start sends it back only once it has changed.
            with self._lock:
                self._outcome(name).keeper_saved = _digest(data)
            restored.append(name)
        if restored:
            logger.info("state: restored %d file(s) from the %s keeper: %s",
                        len(restored), registration.name, ", ".join(restored))

    def take_stock(self) -> None:
        """Read the directory once, at startup after the keeper's restore: which
        files are there and when each was last written, and which ``.bak`` files
        an earlier process set aside (ADR-0077) — so the report can say so for
        the life of the process without touching the disk again (ADR-0072). A
        stamp this layer already recorded, by writing the file, stands."""
        try:
            entries = [entry for entry in self._directory.iterdir()
                       if entry.is_file() and not entry.name.endswith(TEMP_SUFFIX)]
        except OSError:
            return
        stamps: dict[str, float] = {}
        for entry in entries:
            try:
                stamps[entry.name] = entry.stat().st_mtime
            except OSError:
                continue
        with self._lock:
            for name, stamp in stamps.items():
                self._stamps.setdefault(name, stamp)

    def _save_to_keeper(self) -> None:
        """Mirror the directory to the keeper — every file, not only the ones this
        process writes, because a package's own file under here is state too and a
        keeper never knows what it carries.

        Runs at the end of :meth:`flush`, which is *after* the writer and on the
        same interval, and once more at graceful shutdown. A file whose bytes the
        keeper already took is not sent again. A save that raises is a WARN line
        naming the file and the keeper until one of that file lands; the rest are
        still sent, and nothing here reaches the caller — a keeper cannot take the
        tick down.
        """
        registration = registered_keeper()
        if registration is None:
            return
        self._keeper_name = registration.name
        for name in self._state_files():
            try:
                data = self.path(name).read_bytes()
            except OSError:
                continue          # written and replaced under us; the next flush has it
            digest = _digest(data)
            with self._lock:
                outcome = self._outcome(name)
                if outcome.held or outcome.keeper_saved == digest:
                    continue
            try:
                registration.keeper.save(name, data)
            except Exception as error:
                with self._lock:
                    self._outcome(name).keeper_error = repr(error)
                logger.warning("state: the %s keeper could not take %s: %r; the "
                               "local file stands", registration.name, name, error)
                continue
            with self._lock:
                outcome = self._outcome(name)
                outcome.keeper_saved = digest
                outcome.keeper_error = ""

    # --- adoption (ADR-0077) ---

    def _adopt_from_keeper(self) -> bool:
        """The takeover: ask the keeper which files the store changed since this
        instance last synced with it, and adopt every one — the running process
        first, then the local file set aside as ``.bak`` and the store's copy in
        its place. Returns whether the ask succeeded, which is whether this
        interval's saves may run: an answer that raises, or names something that
        is not a state file name, is the keeper's tick failing — the WARN line
        that already exists — and no save runs behind it. A file that could not
        be adopted is its own ERROR line and stops nothing else.
        """
        registration = registered_keeper()
        if registration is None:
            return False
        keeper = registration.keeper
        try:
            names = changed_since_sync(keeper)
        except Exception as error:
            return self._takeover_failed(
                f"asking what changed since the last sync failed: {error!r}")
        for name in names:
            if not _is_plain_name(name):
                return self._takeover_failed(
                    f"it named {name!r} as changed, which is not a state file name")
        # Registered files first, in registration order — the event log before the
        # pins whose adoption writes transitions into it — then whatever else the
        # keeper named, as it named it, then whatever is still held from before.
        with self._lock:
            registered = [name for name in self._files if name in names]
            held = [name for name, outcome in self._outcomes.items()
                    if outcome.held]
        ordered = list(dict.fromkeys(
            registered + [name for name in names if name not in registered] + held))
        adopted = self._adopt_from_store(keeper, ordered)
        if adopted:
            logger.info("state: took over — adopted %d file(s) the store changed "
                        "since this instance last synced with the %s keeper: %s; "
                        "what each replaced is beside it as %s",
                        len(adopted), registration.name, ", ".join(adopted),
                        BACKUP_SUFFIX)
        return True

    def _retry_held(self) -> None:
        """Every interval the keeper takes saves and no flip happened: adopt again
        every file whose last adoption failed, by name — the keeper is not asked
        what changed, because a token that differs from *our* last save (one that
        failed) would name a file this instance rightly holds newer, and adopting
        the store's copy of that would overwrite it. The hold lifts when the
        adoption lands."""
        registration = registered_keeper()
        if registration is None:
            return
        with self._lock:
            held = [name for name, outcome in self._outcomes.items()
                    if outcome.held]
        if held:
            adopted = self._adopt_from_store(registration.keeper, held)
            if adopted:
                logger.info("state: adopted %s from the %s keeper on retry; the "
                            "hold on its save is lifted", ", ".join(adopted),
                            registration.name)

    def _adopt_from_store(self, keeper: Keeper, names: list[str]) -> list[str]:
        """Fetch and adopt each of ``names`` from the keeper, in that order; the
        names adopted. A copy that cannot be fetched is the ERROR line and a hold
        on the file's save; a name the store holds nothing for lifts any hold,
        since there is nothing there to overwrite; and a copy whose bytes are the
        local file's already is nothing to adopt — the digest is seeded and no
        ``.bak`` is made of a file for its own copy."""
        adopted: list[str] = []
        for name in names:
            try:
                data = keeper.load(name)
            except Exception as error:
                self._adoption_failed(
                    name, f"the store's copy of {name} could not be adopted at "
                          f"takeover: fetching it failed ({error!r}); what the "
                          f"last holder wrote is not in force, and this "
                          f"instance's copy is held out of the mirror until it is",
                    hold=True)
                continue
            if data is None:
                # Named as changed and then gone: nothing to adopt, nothing claimed,
                # and nothing a save of the local file could overwrite.
                logger.info("state: the %s keeper holds nothing for %s, which it "
                            "named as changed", self._keeper_name, name)
                with self._lock:
                    self._outcome(name).held = False
                continue
            if self._same_as_local(name, data):
                logger.info("state: the %s keeper named %s as changed, but its copy "
                            "is byte for byte the local file; nothing to adopt",
                            self._keeper_name, name)
                with self._lock:
                    outcome = self._outcome(name)
                    outcome.held = False
                    outcome.keeper_saved = _digest(data)
                continue
            if self._adopt(name, data, what="the store's copy", from_store=True):
                adopted.append(name)
        return adopted

    def _same_as_local(self, name: str, data: bytes) -> bool:
        """Whether ``data`` is the local file's bytes already — a store whose
        token moved without its bytes moving (a version, an encrypted PUT)."""
        try:
            return self.path(name).read_bytes() == data
        except OSError:
            return False

    def _takeover_failed(self, detail: str) -> bool:
        with self._lock:
            self._keeper_tick_error = detail
        logger.warning("state: the %s keeper's takeover failed: %s; no save this "
                       "interval", self._keeper_name, detail)
        return False

    def _adopt(self, name: str, data: bytes, *, what: str,
               from_store: bool) -> bool:
        """Adopt ``data`` as state file ``name`` (ADR-0077): hand the parsed
        payload to the file's ``restore`` where one is registered, then swap it
        in on disk — ``data`` written to the temporary file, the live file set
        aside as ``<name>.bak`` (an older one overwritten), the temporary file
        renamed into place. The process first and the disk second, so a payload
        the process cannot take changes nothing; and the temporary file first on
        disk, so the one step that can fail there fails before anything has
        moved, and no moment leaves the live file gone. ``what`` names the copy in
        a line — *the store's copy*, *the backup* — and ``from_store`` says the
        keeper already holds these bytes, so the mirror need not send them back
        until they change, and that a failure holds the file out of the mirror
        until an adoption lands, since what is on disk is then this instance's
        shadow. Returns whether the file is adopted where it can be.

        Call only while holding the swap lock.
        """
        with self._lock:
            registered = self._files.get(name)
            restore = registered.restore if registered is not None else None
        if restore is not None:
            try:
                payload = json.loads(data.decode("utf-8"))
            except ValueError as error:
                self._adoption_failed(
                    name, f"{what} of {name} could not be adopted: it is not JSON "
                          f"({error}); what the process holds stands"
                          + (", held out of the mirror" if from_store else ""),
                    hold=from_store)
                return False
            try:
                restore(payload)
            except Exception as error:
                logger.exception("state: the restore of %s raised", name)
                self._adoption_failed(
                    name, f"{what} of {name} could not be adopted: taking it in "
                          f"raised {error!r}; what the process holds stands"
                          + (", held out of the mirror" if from_store else ""),
                    hold=from_store)
                return False
        try:
            self._swap_in(name, data)
        except OSError as error:
            # Nothing moved: the temporary file is the step that fails. What the
            # process holds is the adopted copy where it had a restore, and the
            # disk is behind it until this lands or the next write from memory.
            self._adoption_failed(
                name, f"{what} of {name} could not be put in place ({error}); "
                      f"the file on disk is behind what the process holds"
                      + (", and held out of the mirror" if from_store else ""),
                hold=from_store)
            return False
        with self._lock:
            outcome = self._outcome(name)
            outcome.load_error = ""
            outcome.save_error = ""
            outcome.held = False
            outcome.keeper_saved = _digest(data) if from_store else ""
            if restore is None:
                outcome.adopted = (
                    f"{what} of {name} was written in place, but nothing in this "
                    f"process is registered to take it; what the process holds is "
                    f"its own until a restart")
                outcome.adopted_code = StatusCode.WARN
            else:
                outcome.adopted = ""
            if registered is not None and registered.producer is not None:
                registered.written = _digest(data)
        return True

    def _adoption_failed(self, name: str, line: str, *, hold: bool = False) -> None:
        with self._lock:
            outcome = self._outcome(name)
            outcome.adopted = line
            outcome.adopted_code = StatusCode.ERROR
            if hold:
                outcome.held = True
        logger.error("state: %s", line)

    def _swap_in(self, name: str, data: bytes) -> None:
        """Put ``data`` in place as ``name`` with what was there kept as
        ``<name>.bak``: the temporary file first, then the live file set aside,
        then the temporary file renamed over it — two renames in one directory
        after the one write that can fail. Raises :class:`OSError`: with nothing
        moved when the write fails, and with the live file put back from
        ``.bak`` in the one case that can fail after it moved, the last rename.
        """
        path = self.path(name)
        tmp = path.with_name(path.name + TEMP_SUFFIX)
        self._directory.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as handle:
            handle.write(data)
        set_aside = False
        try:
            set_aside = self._set_aside(name)
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            if set_aside:
                self._put_back(name)
            raise
        with self._lock:
            self._stamps[name] = self._wall()

    def _put_back(self, name: str) -> None:
        """Undo :meth:`_set_aside` — the ``.bak`` renamed to the live name, its
        stamp with it — after the rename that should have followed it failed.
        A refusal here is logged and not raised: the caller is already raising
        the failure that matters, and the copy is still there as ``.bak``."""
        path = self.path(name)
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        try:
            os.replace(backup, path)
        except OSError as error:
            # Log-only on purpose: the caller reports the adoption that failed
            # as the file's line, and this is the detail of what it left behind.
            logger.warning("state: %s could not be put back from %s after the "
                           "swap failed: %s; the copy stands as %s", name,
                           backup.name, error, backup.name)
            return
        with self._lock:
            stamp = self._stamps.pop(backup.name, None)
            if stamp is not None:
                self._stamps[name] = stamp

    def _set_aside(self, name: str) -> bool:
        """Rename the live ``name`` to ``<name>.bak``, over an older one, and move
        its stamp along — the backup is as old as what it was. ``False`` where
        there was no live file; any other refusal is the caller's."""
        path = self.path(name)
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        try:
            os.replace(path, backup)
        except FileNotFoundError:
            return False
        with self._lock:
            stamp = self._stamps.pop(name, None)
            if stamp is None:
                try:
                    stamp = backup.stat().st_mtime
                except OSError:
                    stamp = self._wall()
            self._stamps[backup.name] = stamp
        return True

    def take_backups(self) -> str:
        """*Take the backups* (ADR-0077): for every ``<name>.bak`` beside a file
        this layer keeps or restores, the live file is set aside as ``.bak`` in
        turn and the backup written back and handed to the same ``restore`` — the
        way back after a takeover, as a second caller of the adoption rather than
        a second mechanism; the keeper then takes what came back, since the store
        holds what was live. A ``.bak`` whose name matches no registered file is
        listed and left alone. Answers the sentence the action shows."""
        with self._swap_lock:
            if not self._may_write():
                return ("nothing was taken back: this instance no longer writes "
                        "its state")
            with self._lock:
                names = [name for name in self._files
                         if name + BACKUP_SUFFIX in self._stamps]
            taken: list[str] = []
            failed: list[str] = []
            for name in names:
                backup = self.path(name + BACKUP_SUFFIX)
                try:
                    data = backup.read_bytes()
                except OSError as error:
                    self._adoption_failed(
                        name, f"the backup of {name} could not be adopted: reading "
                              f"{backup.name} failed ({error}); what the process "
                              f"holds stands")
                    failed.append(name)
                    continue
                if self._adopt(name, data, what="the backup", from_store=False):
                    taken.append(name)
                else:
                    failed.append(name)
        if not taken and not failed:
            return "no backup to take"
        said = []
        if taken:
            said.append(f"took the backup of {', '.join(taken)}; what was live is "
                        f"beside it as {BACKUP_SUFFIX}")
        if failed:
            said.append(f"could not take the backup of {', '.join(failed)} — its "
                        f"line says why")
        return "; ".join(said)

    def _report_keeper_load_failure(self, detail: str) -> None:
        """Record that the keeper could not be read at startup. The first failure
        is the one reported: what follows it is usually the same outage saying so
        once per file, and a line that grew a sentence per state file would be a
        line nobody reads."""
        logger.error("state: the %s keeper could not be read at startup: %s; "
                     "starting with the local files", self._keeper_name, detail)
        with self._lock:
            if not self._keeper_load_error:
                self._keeper_load_error = detail

    def _state_files(self) -> list[str]:
        """Every state file in the directory, in name order — what a keeper
        mirrors. Half-written files are not state, a ``.bak`` is this machine's
        own (ADR-0077), and directories are not files."""
        try:
            return sorted(entry.name for entry in self._directory.iterdir()
                          if entry.is_file()
                          and not entry.name.endswith(TEMP_SUFFIX)
                          and not entry.name.endswith(BACKUP_SUFFIX))
        except OSError:
            return []

    # --- the report ---

    def lines(self) -> tuple[Entry, ...]:
        """What the heartbeat says about this layer — the self-report contributor
        (ADR-0071). Per file, at most three lines, each with a stable slug: a
        **load failure** at ERROR while it stands, because what somebody set
        before the restart is not in force — or, under the same slug, what an
        **adoption** left standing (ADR-0077): ERROR for a copy the process could
        not take in, WARN for one written to disk that nothing in the process
        takes; a **failed save** at WARN, because nothing is lost yet and the next
        restart is; and the same WARN for a save the **keeper** would not take,
        where what is lost is not the restart but the next machine. The keeper's
        own load failure is one ERROR line above them all, for the same reason
        the per-file one is. Every line carries a code; what the layer merely
        knows — the ``.bak`` files — is :meth:`report`. Recorded state, read:
        nothing here touches the disk."""
        from little_sister.checks import plain
        with self._lock:
            keeper_name = self._keeper_name
            keeper_load_error = self._keeper_load_error
            keeper_tick_error = self._keeper_tick_error
            outcomes = [(name, outcome.load_error, outcome.save_error,
                         outcome.keeper_error, outcome.adopted,
                         outcome.adopted_code)
                        for name, outcome in sorted(self._outcomes.items())]
        lines: list[Entry] = []
        if keeper_load_error:
            lines.append(Entry(
                "keeper.load",
                plain(f"the state could not be loaded from the {keeper_name} "
                      f"keeper at startup ({keeper_load_error}); what it held "
                      f"before the restart is not in force"),
                code=StatusCode.ERROR))
        if keeper_tick_error:
            lines.append(Entry(
                "keeper.tick",
                plain(f"the {keeper_name} keeper's last tick failed "
                      f"({keeper_tick_error}), so nothing was saved to it that "
                      f"interval; nothing is lost yet, the next machine is"),
                code=StatusCode.WARN))
        for name, load_error, save_error, keeper_error, adopted, adopted_code \
                in outcomes:
            if adopted:
                lines.append(Entry(f"load.{name}", plain(adopted), code=adopted_code))
            elif load_error:
                lines.append(Entry(
                    f"load.{name}",
                    plain(f"the state in {name} could not be loaded at startup "
                          f"({load_error}); what it held before the restart is "
                          f"not in force"),
                    code=StatusCode.ERROR))
            if save_error:
                lines.append(Entry(
                    f"save.{name}",
                    plain(f"the last save of {name} failed ({save_error}); "
                          f"nothing is lost yet, the next restart is"),
                    code=StatusCode.WARN))
            if keeper_error:
                lines.append(Entry(
                    f"keeper.save.{name}",
                    plain(f"the last save of {name} to the {keeper_name} keeper "
                          f"failed ({keeper_error}); nothing is lost yet, the "
                          f"next machine is"),
                    code=StatusCode.WARN))
        return tuple(lines)

    def report(self) -> str:
        """What the layer **knows** and does not claim — the ``state`` child's
        `report` (ADR-0044 decision 6, ADR-0076): one item per ``.bak`` in the
        directory, what was set aside and when, beside the live copy's own stamp,
        both local files on one clock — which is what *take the backups* would
        swap. Markdown; ``""`` with nothing set aside. Recorded state, read from
        the stock: nothing here touches the disk."""
        from little_sister.checks import plain
        with self._lock:
            backups = [(name[:-len(BACKUP_SUFFIX)], stamp,
                        self._stamps.get(name[:-len(BACKUP_SUFFIX)]),
                        name[:-len(BACKUP_SUFFIX)] in self._files)
                       for name, stamp in sorted(self._stamps.items())
                       if name.endswith(BACKUP_SUFFIX)]
        if not backups:
            return ""
        now = self._wall()
        items: list[str] = []
        for name, stamp, live_stamp, registered in backups:
            # The names are the directory's and are folded in as external text;
            # the sentence around them is ours, and the action's name is set in
            # italics the way the button spells it.
            backup, live = plain(name + BACKUP_SUFFIX), plain(name)
            age = coarse_span(max(0.0, now - stamp))
            if live_stamp is None:
                beside = f"there is no live {live}"
            else:
                beside = (f"the live {live} was written "
                          f"{coarse_span(max(0.0, now - live_stamp))} ago")
            if registered:
                items.append(f"- {backup} holds what was set aside, last written "
                             f"{age} ago; {beside} — *take the backups* swaps them")
            else:
                items.append(f"- {backup} is a backup of a file nothing here keeps, "
                             f"last written {age} ago; {beside} — listed, not taken")
        return "Set aside (ADR-0077):\n\n" + "\n".join(items)

    def _outcome(self, name: str) -> _Outcome:
        # Call only while holding the lock.
        return self._outcomes.setdefault(name, _Outcome())


def _dumps(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_plain_name(name: str) -> bool:
    """Whether ``name`` is usable as a state file name in this directory and
    nothing else — no separator, no drive, not a walk upwards, and not what this
    layer sets aside or is halfway through writing: a store that offers
    ``maintenance.json.bak`` is not offering a state file (ADR-0077). It guards
    the two places a name arrives from outside the library: a keeper's listing,
    and its answer at a takeover."""
    return bool(name) and name not in (".", "..") and os.sep not in name \
        and (os.altsep or os.sep) not in name and not os.path.isabs(name) \
        and not name.endswith((BACKUP_SUFFIX, TEMP_SUFFIX))
