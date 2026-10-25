"""The state layer: what a restart keeps, as files under ``var/state/`` (ADR-0071).

Three layers hold what this process wants to survive a restart. **Memory** is
where the application works (ADR-0001/0002). **This layer** is memory serialized
to JSON files under ``var/state/`` and read back at startup, so an instance
initializes with what it had — the pins, the event log, the series,
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
the same directory and :func:`os.replace`, the discipline the pins' file always
had, so a reader never sees half a file.

**The name says the encoding** (ADR-0134). The event log and the series are
compact JSON under gzip, ``events.json.gz`` and ``series.json.gz`` — ``gzip -dc``
reads one — and ``pins.json`` stays plain. ``events.json``, ``series.json`` and
``maintenance.json`` are retired names: never read, and named where a start or a
takeover meets one. Every file the layer writes carries its **generation** beside
its own tables — the writer's mark, its count of writes of that file, and whether
it held the keeper's lease as it wrote — and a reader is handed the tables without
it. A file is rewritten only when its content changed, judged without the
generation, so the count moves with the content and never alone.

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
swaps them back through the same adoption. At a **start** the store's copy wins
over a local one but for one case: a local copy newer by the same writer, written
holding — the dead worker's state, when the next one starts on the same disk
(ADR-0134 decision 5).

**Two cadences to the keeper** (ADR-0134 decision 6). What an operator sets — a
file written through — goes at the next scheduler tick after it changes, where the
keeper answers ``push``; what is observed — a kept file — every
``keeper_interval`` while nobody stands by and every interval while anyone does,
by the keeper's ``standing_by``. A takeover, the stop's one save and the two
flushes an action runs between send everything at once. The disk keeps
``state_interval``.

The files are JSON because they are machine-written and machine-read; YAML stays
for what a person authors. Nothing else loose in ``var/`` is state: logs, pids
and TLS material stay where they are.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from little_sister.codes import StatusCode
from little_sister.instance import this_instance
from little_sister.keeper import (
    Keeper,
    Registration,
    changed_since_sync,
    close_keeper,
    push,
    registered_keeper,
    standing_by,
    takes_saves,
)
from little_sister.logger import logger
from little_sister.reasons import Entry
from little_sister.spans import coarse_span

if TYPE_CHECKING:
    from little_sister.lease import Lease

#: Fixed runtime path, relative to the working directory a deployment is started
#: from (ADR-0071) and git-ignored; not env-overridable, like the maintenance file
#: before it (ADR-0014).
STATE_DIR = "var/state"

#: How often the kept files are written, in seconds, unless ``settings.yaml``
#: says otherwise.
DEFAULT_STATE_INTERVAL = 60

#: How often the observed state — the kept files — goes to a keeper while nobody
#: stands by, in seconds, unless ``settings.yaml`` says otherwise (ADR-0134
#: decision 6): met at the first flush after it falls due, so never shorter, in
#: effect, than the state interval.
DEFAULT_KEEPER_INTERVAL = 900

#: The pins (ADR-0141), written through by the tree: what a person set on a node or
#: on one of its lines. Plain JSON under its name: small, written through, and the
#: file an operator reads.
PINS_FILE = "pins.json"

#: A node's notes (ADR-0047, ADR-0140), written through by the notes' book. Plain
#: JSON under its name, as the pins are: written by a person, and the file an
#: operator reads; an archive rather than current state, so a file of its own.
NOTES_FILE = "notes.json"

#: What a name ends in when its file is compact JSON under gzip (ADR-0134 decision
#: 1): the name says the encoding, on a disk and in a bucket alike.
COMPRESSED_SUFFIX = ".gz"

#: The event log (ADR-0001), kept periodically, compressed; node history is
#: derived from it.
EVENTS_FILE = "events.json.gz"

#: The series (ADR-0087), kept periodically, compressed: every subject's kept
#: readings, so a restarted instance shows yesterday's records and a keeper
#: carries them with the rest.
SERIES_FILE = "series.json.gz"

class Retired(NamedTuple):
    """A name a state file was kept under before a release that broke with it: the
    name that took its place, what it held, the record that says why, and what is
    not in force for it."""
    successor: str
    what: str
    record: str
    lost: str


#: The names state was kept under before a clean break, each with the name that took
#: its place: the event log and the series before ADR-0134, and the maintenance pins
#: before ADR-0141 made every pin one file. No release from then on reads one
#: (ADR-0134 decision 2): a start that finds one without its successor, and a
#: takeover that adopts one from a holder of a release before, say so on the
#: ``load.`` slug.
RETIRED_FILES: Mapping[str, Retired] = {
    "events.json": Retired(EVENTS_FILE, "the event log", "ADR-0134",
                           "the history begins at the upgrade"),
    "series.json": Retired(SERIES_FILE, "the series", "ADR-0134",
                           "the history begins at the upgrade"),
    "maintenance.json": Retired(PINS_FILE, "the pins", "ADR-0141",
                                "a pin set before the upgrade holds nothing "
                                "until it is set again"),
}

#: The top-level key every file the layer writes carries its generation under,
#: beside the file's own tables (ADR-0134 decision 4).
GENERATION = "generation"

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
    #: When a save of this file last landed with the keeper, on the layer's clock:
    #: a kept file's next one waits ``keeper_interval`` from it while nobody stands
    #: by, since the interval counts from each send (ADR-0134 decision 6).
    keeper_sent_at: float | None = None
    #: The line a **retired** name stands under ``load.<name>`` (ADR-0134 decision
    #: 2) — a start that found it without its successor, or a takeover that wrote
    #: it in place — for the life of the process: it is never read again.
    retired: str = ""


@dataclass(frozen=True)
class Generation:
    """Who wrote a file, and how many writes of it that was (ADR-0134 decision 4):
    the writer's mark (ADR-0074), its count of writes of the file from 1, and
    whether the keeper took its saves the interval before — what the layer knew
    as it wrote, since the files are written before the keeper's tick. A start
    keeps a local copy over the store's by it, and compares no two clocks."""
    writer: str
    count: int
    held: bool

    def to_dict(self) -> dict[str, Any]:
        return {"writer": self.writer, "count": self.count, "held": self.held}

    @staticmethod
    def of(payload: object) -> Generation | None:
        """The generation a parsed file carries, or ``None`` where it carries none
        — every release before ADR-0134 wrote none, and a package's file never
        does — or one of another shape, which is no generation either."""
        if not isinstance(payload, Mapping):
            return None
        raw = payload.get(GENERATION)
        if not isinstance(raw, Mapping):
            return None
        writer, count, held = raw.get("writer"), raw.get("count"), raw.get("held")
        if not isinstance(writer, str) or not writer:
            return None
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            return None
        if not isinstance(held, bool):
            return None
        return Generation(writer, count, held)

    def supersedes(self, theirs: Generation) -> bool:
        """Whether a local copy stamped so is the newer of the two at a start: the
        same writer as the store's copy, a higher count, and written holding — the
        dead worker's newer state on the same disk. A standby's writes never are:
        written without the lease, they stay the shadow ADR-0077 makes them."""
        return (self.held and self.writer == theirs.writer
                and self.count > theirs.count)


class StateLayer:
    """The directory of state files, the two write disciplines, and what each
    file's last load and save came to."""

    def __init__(self, directory: str | Path = STATE_DIR, *,
                 interval_seconds: int = DEFAULT_STATE_INTERVAL,
                 keeper_interval_seconds: int = DEFAULT_KEEPER_INTERVAL,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 writer: str | None = None) -> None:
        self._directory = Path(directory)
        self._interval = max(1, int(interval_seconds))
        self._keeper_interval = max(1, int(keeper_interval_seconds))
        self._clock = clock
        # The mark a generation names its writer by (ADR-0134 decision 4): this
        # process's (ADR-0074), asked for at the first write — a test names one so
        # that two layers in one process can be two writers.
        self._writer = writer
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
        #: The digest of each file's content as this layer last wrote it — or as
        #: an adoption put it in place — without its generation (ADR-0134 decision
        #: 1), so an unchanged state is not rewritten and its count does not move:
        #: a file that did not change is not a file to touch. The digest and never
        #: the text, which for the series is megabytes the process would hold for
        #: its whole life only to compare them with the next text.
        self._written: dict[str, str] = {}
        #: This writer's count of writes of each file, the generation's ``count``.
        self._counts: dict[str, int] = {}
        #: The files written through since the keeper last took them — what an
        #: operator set — pushed at the next scheduler tick (ADR-0134 decision 6).
        self._pending: set[str] = set()
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
        #: Why the keeper's last ``standing_by`` raised; cleared by the next answer.
        #: Meanwhile it counts as watched, and the observed state goes every interval.
        self._keeper_standby_error = ""
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
        """The parsed JSON of state file ``name``, decoded as its name says — a
        compressed one gunzipped first (ADR-0134) — and without the generation the
        layer stamped on it: what its producer wrote, which is all a reader takes.

        ``None`` when there is no file — a first start, or a state never written
        — and also when the file cannot be read or does not decode — not JSON, or
        for a compressed one not gzip, cut short or damaged — which is a **load
        failure**: recorded, logged, and a line on the heartbeat for as long as the
        process runs. The caller starts that state empty either way; it never
        refuses to start over a file (ADR-0071).
        """
        try:
            data = self.path(name).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            self.report_load_failure(name, str(error))
            return None
        try:
            return _tables(_decode(name, data))
        except ValueError as error:
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
        """Write ``payload`` — a JSON object — as state file ``name`` now, the
        write-through discipline, atomically and stamped with this writer's next
        generation (ADR-0134 decision 4); the keeper is handed it at the next
        scheduler tick (decision 6). A payload whose content is what the file
        holds already is not written again, and its count does not move. A
        failure is logged and recorded, never raised: the state stays in memory
        for the session, and the heartbeat says the file is behind until a later
        write succeeds. After the stop, or once the lease is lost, nothing is
        written and the answer is ``False``."""
        if not self._may_write():
            return False
        digest = _digest(_content(payload))
        with self._lock:
            if self._written.get(name) == digest:
                # The disk holds this content already — nothing is behind.
                self._outcome(name).save_error = ""
                return True
        if not self._write_stamped(name, payload):
            return False
        with self._lock:
            self._written[name] = digest
            self._pending.add(name)
        return True

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
            self._written.pop(name, None)
            if restore is not None:
                registered.restore = restore

    def restore_with(self, name: str, restore: Restore) -> None:
        """Register the other direction of a file the process **writes through**
        (ADR-0077) — the pins, whose producer is the write
        itself: ``restore`` takes the parsed payload of an adopted copy and
        replaces what the process holds. The same callable :meth:`keep` takes,
        for a file that has no producer to register beside it."""
        with self._lock:
            self._files.setdefault(name, _Registered()).restore = restore

    def tick(self) -> bool:
        """The scheduler's call, once per tick: hand the keeper what an operator
        set since the last tick (ADR-0134 decision 6), then write the kept files
        when an interval has passed since the last time, and say whether this tick
        ran that save — the engine's tick line says so (ADR-0095 decision 5). The
        first tick only starts the interval — there is nothing to write yet that
        startup did not just read. The keeper takes the observed state on its own
        cadence, ``keeper_interval`` while nobody stands by."""
        self._push_pending()
        now = self._clock()
        with self._lock:
            if self._last_flush is None:
                self._last_flush = now
                return False
            if now - self._last_flush < self._interval:
                return False
            self._last_flush = now
        with self._swap_lock:
            if not self._may_write():
                return False
            self._flush(everything=False)
            return True

    def flush(self) -> bool:
        """Write every kept file whose state changed since its last write, and
        send the keeper **everything** that changed, whatever ``keeper_interval``
        says (ADR-0134 decision 6) — the stop's one save, and the two an action
        runs between: the one before its handler sends what the process holds
        while the lease is still its own, which a keeper's release gives up in its
        handler, and the one after it what the action changed, now rather than at
        the next interval (ADR-0076 decision 6). A producer that raises is a failed
        save of its file, reported like any other, and the rest are still written.
        Then the keeper: its tick, the adoption where that tick is a takeover
        (ADR-0077), and the saves it takes. ``False`` where the layer may no longer
        write and nothing ran."""
        with self._swap_lock:
            if not self._may_write():
                return False
            self._flush(everything=True)
            return True

    def _flush(self, *, everything: bool) -> None:
        # Call only while holding the swap lock.
        with self._lock:
            kept = [(name, item) for name, item in self._files.items()
                    if item.producer is not None]
        for name, item in kept:
            assert item.producer is not None
            try:
                payload = item.producer()
                if not isinstance(payload, Mapping):
                    raise TypeError(f"a state file is a JSON object, not "
                                    f"{type(payload).__name__}")
                digest = _digest(_content(payload))
            except Exception as error:
                logger.exception("state: the producer of %s raised", name)
                with self._lock:
                    self._outcome(name).save_error = (
                        f"its producer raised: {error!r}")
                continue
            with self._lock:
                if self._written.get(name) == digest:
                    continue
            if self._write_stamped(name, payload):
                with self._lock:
                    self._written[name] = digest
        # The keeper, after the writer and on the same interval (ADR-0071 §5), so
        # what it takes is what this tick just wrote rather than the tick before —
        # and only when its tick says so: a keeper that is not the holder of its
        # store this interval takes nothing, and nothing here counts that as a save.
        wanted = self._tick_keeper()
        flip = wanted and not self._taking
        if flip:
            # The flip — a standby became the holder, or a demoted holder took
            # the lease back: whoever held it wrote the truth meanwhile, so what
            # the store changed is adopted before this interval's first save
            # (ADR-0077). An ask that fails takes no save behind it, and is asked
            # again next interval.
            wanted = self._adopt_from_keeper()
        elif wanted:
            self._retry_held()
        if wanted:
            # The flip's save sends the observed state at once, so the store holds
            # the new holder's copies from its first interval as holder
            # (ADR-0134 decision 6).
            self._save_to_keeper(observed=everything or flip)
        self._taking = wanted

    def shutdown(self) -> None:
        """The graceful end — the stop's one save (ADR-0088 decision 3): the last
        flush, which sends the keeper everything (ADR-0134 decision 6), then the
        keeper's ``close``, after the last save so what a lease
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

    def _watched(self, registration: Registration) -> bool:
        """Whether another instance stands by, as the keeper last saw — asked after
        its tick, before the saves (ADR-0134 decision 6). A keeper without
        ``standing_by`` counts as always watched, and so does one whose answer
        raises, which is a WARN line until it answers: the observed state goes
        every interval meanwhile, as it did before the method existed."""
        try:
            watched = standing_by(registration.keeper)
        except Exception as error:
            with self._lock:
                self._keeper_standby_error = repr(error)
            logger.warning("state: the %s keeper could not say whether another "
                           "instance stands by: %r; the event log and the series "
                           "go to it every interval meanwhile", registration.name,
                           error)
            return True
        with self._lock:
            self._keeper_standby_error = ""
        return watched

    def _push_pending(self) -> None:
        """What an operator set goes to the store at the next scheduler tick after
        it changes (ADR-0134 decision 6): every file written through since the
        keeper last took it, handed to the keeper's ``push`` — which lands it only
        behind a heartbeat of its own, so only while the lease is held — where the
        keeper took the last interval's saves. A keeper without ``push`` is handed
        them with the interval's saves, as before; a standby pushes nothing, since
        its writes are the shadow ADR-0077 makes them. A push that raises is the
        save line of its file, and the interval's saves send it again."""
        with self._lock:
            if not self._pending:
                return
            names = sorted(self._pending)
            self._pending.clear()
        registration = registered_keeper()
        if registration is None:
            return
        self._keeper_name = registration.name
        with self._swap_lock:
            if not self._may_write() or not self._taking:
                return
            for name in names:
                try:
                    data = self.path(name).read_bytes()
                except OSError:
                    continue          # replaced under us; the interval has it
                digest = _digest(data)
                with self._lock:
                    outcome = self._outcome(name)
                    if outcome.held or outcome.keeper_saved == digest:
                        continue
                try:
                    pushed = push(registration.keeper, name, data)
                except Exception as error:
                    with self._lock:
                        self._outcome(name).keeper_error = repr(error)
                    logger.warning("state: the %s keeper could not take %s between "
                                   "its ticks: %r; it goes with the interval's "
                                   "saves", registration.name, name, error)
                    continue
                if not pushed:
                    return            # no push: the interval's saves carry them
                with self._lock:
                    outcome = self._outcome(name)
                    outcome.keeper_saved = digest
                    outcome.keeper_error = ""

    def _write_stamped(self, name: str, payload: object) -> bool:
        """Write ``payload`` as ``name``, encoded as its name says (ADR-0134
        decision 1) and stamped with this writer's next generation (decision 4):
        ``held`` is whether the keeper took its saves the interval before — what
        the layer knows as it writes, since the files are written before the
        keeper's tick — so a start's first write says false, and where no keeper
        is registered it is true. The count moves only with a write that landed."""
        with self._lock:
            count = self._counts.get(name, 0) + 1
        held = registered_keeper() is None or self._taking
        data = _encode(name, _stamped(payload, Generation(self._mark(), count,
                                                          held)))
        if not self._write_bytes(name, data):
            return False
        with self._lock:
            self._counts[name] = count
        return True

    def _mark(self) -> str:
        if self._writer is None:
            self._writer = this_instance().mark
        return self._writer

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
        over a local file of the same name — which is the point on a new machine.
        On an old one the store's copy is the older where a save to the keeper
        failed, which the WARN line below has said ever since, and where the
        observed state waited for ``keeper_interval`` — which is the one case below.

        **But for one case** (ADR-0134 decision 5): a local copy whose generation
        names the same writer as the store's, a higher count, and ``held`` is the
        dead worker's newer state when the next starts on the same disk, and
        stays. Every copy is still fetched — a keeper notes the store's token as
        it loads, so the flip that follows names nothing for a copy the layer did
        not put in place, and the flip's save sends the newer one up. A copy
        without a generation, as every release before wrote and a package's file
        is, keeps the rule.

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
            if self._newer_here(name, data):
                logger.info("state: kept the local %s over the %s keeper's copy: "
                            "the same writer's, later by its count, and written "
                            "holding (ADR-0134)", name, registration.name)
                with self._lock:
                    self._outcome(name).keeper_saved = _digest(data)
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

    def _newer_here(self, name: str, theirs: bytes) -> bool:
        """Whether the local copy of ``name`` supersedes the store's ``theirs`` by
        their generations (ADR-0134 decision 5). Only a file the layer could have
        written is decoded for it — a JSON name, plain or compressed — so a
        package's file is never read; a copy that does not decode has no
        generation, and the store's copy wins as it always did."""
        if not name.endswith((".json", ".json" + COMPRESSED_SUFFIX)):
            return False
        try:
            mine = self.path(name).read_bytes()
        except OSError:
            return False
        local, store = _generation_of(name, mine), _generation_of(name, theirs)
        return local is not None and store is not None and local.supersedes(store)

    def take_stock(self) -> None:
        """Read the directory once, at startup after the keeper's restore: which
        files are there and when each was last written, and which ``.bak`` files
        an earlier process set aside (ADR-0077) — so the report can say so for
        the life of the process without touching the disk again (ADR-0072). A
        stamp this layer already recorded, by writing the file, stands.

        A **retired** name found without its successor is the upgrade (ADR-0134
        decision 2): never read, and said twice — in the log at WARN, and on the
        ``load.`` slug for the life of the process — so that whoever looks at the
        instance and not at its log sees why its history begins here."""
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
        for name, retired in RETIRED_FILES.items():
            if name in stamps and retired.successor not in stamps:
                self._retire(name)

    def _retire(self, name: str) -> None:
        """Stand the line of retired name ``name`` (ADR-0134 decision 2), and log
        it at WARN, as ADR-0071 §2 named a maintenance file left at its old path.
        WARN where a load failure is ERROR: what it held went on purpose, and
        nothing an operator does brings it back."""
        line = _retired_line(name)
        with self._lock:
            self._outcome(name).retired = line
        logger.warning("state: %s", line)

    def _save_to_keeper(self, *, observed: bool) -> None:
        """Mirror the directory to the keeper — every file, not only the ones this
        process writes, because a package's own file under here is state too and a
        keeper never knows what it carries.

        Runs at the end of the flush, which is *after* the writer and on the
        same interval, and once more at graceful shutdown. A file whose bytes the
        keeper already took is not sent again. **The observed state — a kept file
        — has a cadence of its own** (ADR-0134 decision 6): every interval while
        another instance stands by, and while nobody does once ``keeper_interval``
        has passed since its last send, unless ``observed`` says it goes now — a
        takeover, the stop, an action. A save that raises is a WARN line naming the
        file and the keeper until one of that file lands; the rest are still sent,
        and nothing here reaches the caller — a keeper cannot take the tick down.
        """
        registration = registered_keeper()
        if registration is None:
            return
        self._keeper_name = registration.name
        with self._lock:
            kept = {name for name, item in self._files.items()
                    if item.producer is not None}
        watched = observed or self._watched(registration)
        now = self._clock()
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
                if (name in kept and not watched
                        and outcome.keeper_sent_at is not None
                        and now - outcome.keeper_sent_at < self._keeper_interval):
                    continue      # not due: the observed state waits its interval
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
                if name in kept:
                    outcome.keeper_sent_at = now

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

        A copy is decoded as its name says (ADR-0134 decision 3): one that does
        not — not JSON, or for a compressed name not gzip, cut short or damaged —
        is a copy that cannot be read, refused like one the process cannot take.
        The ``restore`` is handed the copy's tables without its generation. A
        **retired** name nothing takes in is written in place under its own line,
        which says it is never read — not the one that waits for a restart.

        Call only while holding the swap lock.
        """
        with self._lock:
            registered = self._files.get(name)
            restore = registered.restore if registered is not None else None
        payload: Any = None
        if restore is not None:
            try:
                payload = _tables(_decode(name, data))
            except ValueError as error:
                self._adoption_failed(
                    name, f"{what} of {name} could not be adopted: {error}; what "
                          f"the process holds stands"
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
        retired = restore is None and name in RETIRED_FILES
        with self._lock:
            outcome = self._outcome(name)
            outcome.load_error = ""
            outcome.save_error = ""
            outcome.held = False
            outcome.keeper_saved = _digest(data) if from_store else ""
            if retired:
                outcome.adopted = ""
            elif restore is None:
                outcome.adopted = (
                    f"{what} of {name} was written in place, but nothing in this "
                    f"process is registered to take it; what the process holds is "
                    f"its own until a restart")
                outcome.adopted_code = StatusCode.WARN
            else:
                outcome.adopted = ""
            # What an adoption put in place is what the layer wrote, as far as the
            # next write is concerned: a state that now yields the same content
            # leaves it alone.
            if payload is not None:
                self._written[name] = _digest(_content(payload))
            else:
                self._written.pop(name, None)
        if retired:
            self._retire(name)
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
            keeper_standby_error = self._keeper_standby_error
            outcomes = [(name, outcome.load_error, outcome.save_error,
                         outcome.keeper_error, outcome.adopted,
                         outcome.adopted_code, outcome.retired)
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
        if keeper_standby_error:
            lines.append(Entry(
                "keeper.standing_by",
                plain(f"the {keeper_name} keeper could not say whether another "
                      f"instance stands by ({keeper_standby_error}), so the event "
                      f"log and the series go to it every interval until it can; "
                      f"nothing is lost"),
                code=StatusCode.WARN))
        for name, load_error, save_error, keeper_error, adopted, adopted_code, \
                retired in outcomes:
            if adopted:
                lines.append(Entry(f"load.{name}", plain(adopted), code=adopted_code))
            elif retired:
                lines.append(Entry(f"load.{name}", plain(retired),
                                   code=StatusCode.WARN))
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


def _compact(payload: object) -> bytes:
    """``payload`` as compact JSON with sorted keys, in UTF-8: the same state gives
    the same bytes."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _content(payload: object) -> bytes:
    """What decides whether a file changed: its content before any encoding of the
    file's and without its generation (ADR-0134 decision 1) — never the keeper's
    digest of the bytes it holds."""
    return _compact(_tables(payload))


def _encode(name: str, payload: object) -> bytes:
    """``payload`` as file ``name`` holds it — the name says the encoding (ADR-0134
    decision 1): compact JSON under gzip at level 1 with ``mtime=0`` for a
    compressed name, so the same state gives the same bytes; indented JSON for a
    plain one, which is what an operator reads."""
    if name.endswith(COMPRESSED_SUFFIX):
        return gzip.compress(_compact(payload), compresslevel=1, mtime=0)
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def _decode(name: str, data: bytes) -> Any:
    """The parsed JSON of file ``name``'s bytes, decoded as its name says.
    :class:`ValueError` for every way they are not such a file, because each is
    the one failure ADR-0134 decision 3 names: Python's gzip raises an
    :class:`OSError` for a header or a trailer that is wrong, :class:`EOFError`
    for a stream cut short and :class:`zlib.error` for damaged data — none of which
    a reader of JSON catches. A file cut short is refused, never read short: the
    trailer carries the length and a CRC."""
    if name.endswith(COMPRESSED_SUFFIX):
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError, zlib.error) as error:
            raise ValueError(f"it does not decompress: {type(error).__name__}: "
                             f"{error}") from error
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as error:
        # json.JSONDecodeError and a bad encoding are both ValueErrors.
        raise ValueError(f"it is not JSON: {error}") from error


def _tables(payload: Any) -> Any:
    """A file's payload without the generation the layer stamps on it (ADR-0134
    decision 4): what its producer wrote, and all a reader or a ``restore`` is
    handed."""
    if isinstance(payload, dict) and GENERATION in payload:
        return {key: value for key, value in payload.items() if key != GENERATION}
    return payload


def _stamped(payload: object, generation: Generation) -> dict[str, Any]:
    """``payload`` with ``generation`` beside its tables, as a top-level key — so a
    release before ADR-0134, which takes a file's tables by name, still reads a
    stamped ``maintenance.json``: a stamp wrapped around the tables would have cost
    the pins at a rollback."""
    if not isinstance(payload, Mapping):
        raise TypeError(f"a state file is a JSON object, not "
                        f"{type(payload).__name__}")
    stamped = {key: value for key, value in payload.items() if key != GENERATION}
    stamped[GENERATION] = generation.to_dict()
    return stamped


def _generation_of(name: str, data: bytes) -> Generation | None:
    """The generation file ``name``'s bytes carry, or ``None`` where they carry none
    or do not decode."""
    try:
        return Generation.of(_decode(name, data))
    except ValueError:
        return None


def _retired_line(name: str) -> str:
    """What a retired name stands under its ``load.`` slug (ADR-0134 decision 2)."""
    retired = RETIRED_FILES[name]
    return (f"{name} is no longer read: this release keeps {retired.what} as "
            f"{retired.successor} ({retired.record}), so what it held is not in force "
            f"here — {retired.lost}; the plain copy stays for a rollback, and may be "
            f"deleted once {retired.successor} exists")


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
