"""Every pin leaves an entry that says how it ended (ADR-0145 decisions 4, 5 and 9).

A pin's note enters its node's notes as the pin is set, whatever its kind — one set
without words a record with no text — and keeps its pin's kind, a seen's status and a
silence's level; the write that ends the pin records when, why in the log's words, and
who, where a person ended it, wherever the tree ends one. The notes one act leaves
name one pin's creation, and stand as one entry — on every node the act touched, and
on the node it was made on — which the tab counts and retention keeps or retires
whole.
"""
from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister.notes import (
    Age,
    Context,
    Entry,
    Note,
    NoteBook,
    NoteStore,
    Retention,
    entries_of,
)
from little_sister.pins import MAINTENANCE, SEEN, SILENCED, Pin, PinStore
from little_sister.reasons import Entry as Line
from little_sister.state import StateLayer
from little_sister.status import StatusCode
from little_sister.tree import (
    ENDED_CLOCK,
    ENDED_GONE,
    ENDED_HAND,
    ENDED_MADE,
    ENDED_RECOVERY,
    StatusTree,
)

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
BERLIN = ZoneInfo("Europe/Berlin")


def _utc(*moment: int) -> datetime:
    return datetime(*moment, tzinfo=UTC)


def _maintenance(note: str, created: datetime, *, by: str = "ada") -> Pin:
    return Pin(MAINTENANCE, note, created, created + timedelta(days=1), by)


def _seen(note: str, created: datetime, *, status: StatusCode = ERROR) -> Pin:
    return Pin(SEEN, note, created, None, "ada", status=status)


class _Heard:
    """Who the tree tells of every pin it ends: each end as it was told."""

    def __init__(self) -> None:
        self.ends: list[tuple[str, str, str, str, str]] = []

    def __call__(self, path: str, slug: str, pin: Pin, why: str, by: str,
                 when: datetime) -> None:
        self.ends.append((path, slug, pin.kind, why, by))


def _tree() -> tuple[StatusTree, _Heard]:
    tree = StatusTree()
    heard = _Heard()
    tree.on_pin_end(heard)
    tree.upsert("/db", ERROR, [Line("slow", "queries are slow", code=ERROR),
                               Line("disk", "disk at 91%", code=WARN)], members=True)
    return tree, heard


class NoteRecordsItsPinTests(TestCase):
    """Decision 4: a pin's note keeps its kind, a seen's status and a silence's
    level, and the pin's end."""

    def setUp(self) -> None:
        self.book = NoteBook()

    def test_a_pin_without_words_leaves_a_record_with_no_text(self):
        created = _utc(2026, 10, 25, 9, 12)
        record = self.book.pinned("/db", "slow", _seen("", created), Context())
        self.assertEqual((record.text, record.kind, record.status, record.pin),
                         ("", SEEN, ERROR, instants.stamp(created)))
        self.assertEqual(self.book.count("/db"), 1, "an entry like any other")

    def test_a_silence_keeps_its_level_and_its_note_follows_an_edit_of_it(self):
        created = _utc(2026, 10, 10, 8, 5)
        silence = Pin(SILENCED, "flaky", created, created + timedelta(days=7), "pan",
                      level=WARN)
        note = self.book.pinned("/db", "slow", silence, Context())
        self.assertEqual((note.kind, note.level, note.status), (SILENCED, WARN, None))
        edited = Pin(SILENCED, "flaky", created + timedelta(hours=1),
                     created + timedelta(days=7), "ben", created, "pan", silence.id,
                     level=OK)
        again = self.book.pinned("/db", "slow", edited, Context())
        self.assertEqual((again.key, again.level, again.set_by),
                         (note.key, OK, "ben"), "the same note, the pin's level now")

    def test_its_end_is_recorded_when_why_and_by_whom(self):
        created = _utc(2026, 10, 25, 9, 12)
        pin = _seen("runner image broken", created)
        self.book.pinned("/db", "slow", pin, Context())
        ended = _utc(2026, 10, 25, 11, 40)
        note = self.book.pin_ended("/db", "slow", pin, ENDED_RECOVERY, "", ended)
        assert note is not None
        self.assertEqual((note.ended_at, note.ended, note.ended_by, note.text),
                         (ended, ENDED_RECOVERY, "", "runner image broken"))
        by_hand = self.book.pin_ended("/db", "slow", pin, ENDED_HAND, "lex", ended)
        assert by_hand is not None
        self.assertEqual((by_hand.ended, by_hand.ended_by), (ENDED_HAND, "lex"))

    def test_a_note_written_before_records_its_kind_with_its_end(self):
        # a pin's note of the release before kept no kind; it says what it said,
        # and gains its kind and its end where its pin still stands and ends after
        created = _utc(2026, 10, 25)
        pin = _seen("we know", created, status=WARN)
        before = Note(path="/db", slug="", text="we know", created_at=created,
                      created_by="ada", set_at=created, set_by="ada",
                      pin=instants.stamp(created))
        self.book.restore({"/db": [before]})
        note = self.book.pin_ended("/db", "", pin, ENDED_CLOCK, "",
                                   created + timedelta(hours=2))
        assert note is not None
        self.assertEqual((note.kind, note.status, note.ended),
                         (SEEN, WARN, ENDED_CLOCK))

    def test_a_pin_that_left_no_note_has_none_to_record_its_end_in(self):
        pin = _maintenance("", _utc(2026, 10, 1))
        self.assertIsNone(self.book.pin_ended("/db", "", pin, ENDED_CLOCK, "",
                                              _utc(2026, 10, 2)))
        self.assertEqual(self.book.tables(), {})

    def test_the_record_round_trips_through_the_file(self):
        created = _utc(2026, 10, 25, 9, 12)
        note = Note(path="/db", slug="slow", text="", created_at=created,
                    created_by="ada", set_at=created, set_by="ada",
                    pin=instants.stamp(created), kind=SILENCED, level=WARN,
                    ended_at=created + timedelta(days=7), ended=ENDED_HAND,
                    ended_by="lex", at="/")
        said = note.to_dict()
        self.assertEqual((said["kind"], said["level"], said["ended"], said["ended_by"],
                          said["at"]), (SILENCED, "WARN", ENDED_HAND, "lex", "/"))
        self.assertEqual(Note.from_dict("/db", said), note)
        with self.assertRaisesRegex(ValueError, "no status"):
            Note.from_dict("/db", {**said, "level": "LOUD"})


class OneActOneEntryTests(TestCase):
    """Decision 5: the notes one act leaves name one pin's creation and stand as one
    entry, on every node it touched and on the node it was made on."""

    def setUp(self) -> None:
        self.book = NoteBook()
        self.moment = _utc(2026, 8, 22, 10, 31)
        # one act made on /ci: two lines of /ci/pipelines and /ci/jobs's own failure
        for path, slug in (("/ci/pipelines", "build"), ("/ci/pipelines", "deploy"),
                           ("/ci/jobs", "")):
            self.book.pinned(path, slug, _seen("We know — GitHub outage.",
                                               self.moment), Context(), at="/ci")
        self.book.add("/ci/pipelines", "", "a note of its own", by="lex",
                      context=Context(), now=self.moment + timedelta(days=1))

    def test_on_a_node_it_touched_the_act_is_one_entry(self):
        entries = self.book.entries("/ci/pipelines")
        self.assertEqual([len(entry.notes) for entry in entries], [1, 2],
                         "newest first: the note of its own, then the act's two")
        act = entries[1]
        self.assertEqual({note.slug for note in act.notes}, {"build", "deploy"})
        self.assertEqual(self.book.count("/ci/pipelines"), 2)

    def test_the_node_it_was_made_on_lists_it_and_none_of_the_childrens_own(self):
        entries = self.book.entries("/ci")
        self.assertEqual(len(entries), 1, "the act alone: not the note of its own")
        self.assertEqual({(note.path, note.slug) for note in entries[0].notes},
                         {("/ci/pipelines", "build"), ("/ci/pipelines", "deploy"),
                          ("/ci/jobs", "")})
        self.assertEqual(self.book.count("/ci"), 1)

    def test_a_note_says_where_its_act_was_made_only_where_it_is_another_node(self):
        made_here = self.book.pinned("/ci", "", _seen("its own", self.moment),
                                     Context(), at="/ci")
        self.assertEqual(made_here.at, "")
        (one,) = self.book.of("/ci/jobs")
        self.assertEqual(one.at, "/ci")

    def test_every_part_of_an_act_is_found_wherever_it_stands(self):
        parts = self.book.act(instants.stamp(self.moment))
        self.assertEqual([(note.path, note.slug) for note in parts],
                         [("/ci/jobs", ""), ("/ci/pipelines", "build"),
                          ("/ci/pipelines", "deploy")])
        self.assertEqual(self.book.act(""), (), "a note of its own is no act")

    def test_notes_of_their_own_are_each_an_entry(self):
        first = Note(path="/db", slug="", text="a", created_at=_utc(2026, 1, 1),
                     created_by="ada", set_at=_utc(2026, 1, 1), set_by="ada")
        second = Note(path="/db", slug="", text="b", created_at=_utc(2026, 1, 2),
                      created_by="ada", set_at=_utc(2026, 1, 2), set_by="ada")
        self.assertEqual(entries_of([first, second]),
                         (Entry((second,)), Entry((first,))))


class RetentionByEntriesTests(TestCase):
    """Decision 5: retention counts entries, and keeps or retires an act's notes on a
    node together, by its first note's age."""

    NOW = _utc(2026, 10, 1, 12)

    def test_an_act_counts_once_and_goes_whole(self):
        book = NoteBook()
        old = self.NOW - timedelta(days=900)
        for slug in ("a", "b", "c"):
            book.pinned("/db", slug, _seen("outage", old), Context())
        book.add("/db", "", "recent", by="ada", context=Context(),
                 now=self.NOW - timedelta(days=5))
        # two entries, the floor keeping one: the act is past the ceiling, and its
        # three notes go together
        retention = Retention(keep=1, cap=50, min_age=Age(months=13),
                              max_age=Age(months=25))
        self.assertEqual(book.retire(retention, now=self.NOW, zone=BERLIN), 3)
        self.assertEqual([note.text for note in book.of("/db")], ["recent"])

    def test_the_floor_keeps_entries_not_notes(self):
        book = NoteBook()
        old = self.NOW - timedelta(days=900)
        for slug in ("a", "b", "c"):
            book.pinned("/db", slug, _seen("outage", old), Context())
        # one entry of three notes, the floor two: nothing goes
        retention = Retention(keep=2, cap=1, min_age=Age(seconds=1),
                              max_age=Age(seconds=1))
        self.assertEqual(book.retire(retention, now=self.NOW, zone=BERLIN), 0)
        self.assertEqual(len(book.of("/db")), 3)


class TheTreeTellsEveryEndTests(TestCase):
    """Decision 4: the tree tells who listens of every pin it ends, whatever its
    kind and whatever ended it — and of none an adoption ends."""

    def test_a_hand_says_whose(self):
        tree, heard = _tree()
        soon = datetime.now(UTC) + timedelta(hours=1)
        tree.set_acknowledgment("/db", "slow", SEEN, "known", expires_at=None,
                                set_by="ada")
        tree.set_entry_maintenance("/db", "disk", "swap it", expires_at=soon,
                                   set_by="ada")
        tree.clear_acknowledgment("/db", "slow", by="cy")
        tree.clear_entry_maintenance("/db", "disk", by="ben")
        tree.set_maintenance("/db", "reboot", expires_at=soon, set_by="ada")
        tree.clear_maintenance("/db", by="ben")
        self.assertEqual(heard.ends, [
            ("/db", "slow", SEEN, ENDED_HAND, "cy"),
            ("/db", "disk", MAINTENANCE, ENDED_HAND, "ben"),
            ("/db", "", MAINTENANCE, ENDED_HAND, "ben")])

    def test_the_clock_a_reading_and_a_kind_made_the_other(self):
        tree, heard = _tree()
        soon = datetime.now(UTC) + timedelta(hours=1)
        tree.set_entry_maintenance("/db", "disk", "", expires_at=soon, set_by="ada")
        tree.set_acknowledgment("/db", "slow", SEEN, "", expires_at=None,
                                set_by="ada")
        tree.sweep_expired(now=soon + timedelta(minutes=1))
        tree.upsert("/db", WARN, [Line("slow", "queries are fine", code=OK),
                                  Line("disk", "disk at 91%", code=WARN)],
                    members=True)
        tree.upsert("/db", ERROR, [Line("slow", "queries are slow", code=ERROR),
                                   Line("disk", "disk at 91%", code=WARN)],
                    members=True)
        seen = tree.set_acknowledgment("/db", "slow", SEEN, "", expires_at=None,
                                       set_by="ada").current
        assert seen is not None
        tree.set_acknowledgment("/db", "slow", SILENCED, "", expires_at=soon,
                                set_by="ben", expected_set_at=seen.token, level=OK)
        self.assertEqual(heard.ends, [
            ("/db", "disk", MAINTENANCE, ENDED_CLOCK, ""),
            ("/db", "slow", SEEN, ENDED_RECOVERY, ""),
            ("/db", "slow", SEEN, ENDED_MADE[SILENCED], "ben")])

    def test_a_reap_says_no_longer_reported_and_an_adoption_tells_nobody(self):
        tree, heard = _tree()
        soon = datetime.now(UTC) + timedelta(hours=1)
        tree.set_maintenance("/db", "", expires_at=soon, set_by="ada")
        tree.adopt_maintenance({})
        self.assertEqual(heard.ends, [], "the holder ended it, and its notes say so")
        tree.set_maintenance("/db", "", expires_at=soon, set_by="ada")
        tree.reap_uncovered(["/elsewhere"])
        self.assertEqual(heard.ends, [("/db", "", MAINTENANCE, ENDED_GONE, "")])

    def test_a_pin_that_ran_out_while_down_ended_at_its_end(self):
        tree = StatusTree()
        told: list[tuple[str, str, datetime]] = []
        tree.on_pin_end(lambda path, slug, pin, why, by, when:
                        told.append((slug, why, when)))
        ran_out = _utc(2026, 10, 28, 18)
        pin = Pin(MAINTENANCE, "patch", ran_out - timedelta(days=1), ran_out, "ada")
        tree.restore_maintenance({}, now=ran_out + timedelta(hours=5),
                                 entry_pins={("/db", "disk"): pin})
        self.assertEqual(told, [("disk", ENDED_CLOCK, ran_out)])

    def test_one_listener_is_told_once(self):
        tree, heard = _tree()
        tree.on_pin_end(heard)
        tree.set_maintenance("/db", "", expires_at=datetime.now(UTC)
                             + timedelta(hours=1), set_by="ada")
        tree.clear_maintenance("/db")
        self.assertEqual(len(heard.ends), 1)


class RoutesRecordTests(TestCase):
    """Decision 4 through the routes: every set leaves its record, with what the part
    showed, a head's act on each part saying where it was made, and a clear says
    whose hand."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        self.book = NoteBook()
        self.tree.on_pin_end(self.book.pin_ended)
        for patched in (mock.patch.object(app_module, "status_tree", self.tree),
                        mock.patch.object(app_module, "notes_book", self.book)):
            patched.start()
            self.addCleanup(patched.stop)
        self.tree.upsert("/ci/pipelines", ERROR,
                         [Line("build", "build failed", code=ERROR),
                          Line("lint", "lint failed", code=ERROR)], members=True)
        self.tree.upsert("/ci/jobs", ERROR, "export failed")
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def test_a_head_s_act_leaves_a_record_on_each_part_saying_where(self):
        digest = app_module.parts_digest(app_module._failing_parts("/ci"))
        self.client.post("/pins/seen", data={"path": "/ci", "parts": digest,
                                             "action": "set", "set_at": ""})
        notes = [note for path in ("/ci/pipelines", "/ci/jobs")
                 for note in self.book.of(path)]
        self.assertEqual(sorted((note.path, note.slug, note.text, note.at)
                                for note in notes),
                         [("/ci/jobs", "", "", "/ci"),
                          ("/ci/pipelines", "build", "", "/ci"),
                          ("/ci/pipelines", "lint", "", "/ci")])
        self.assertEqual({note.context.lines[0].text if note.context.lines else ""
                          for note in notes if note.slug},
                         {"build failed", "lint failed"},
                         "each line's note keeps its own line, not its neighbor's")
        self.assertEqual(self.book.count("/ci"), 1)

    def test_a_clear_says_whose_hand(self):
        self.client.post("/pins/maintenance", data={
            "path": "/ci/jobs", "action": "set", "set_at": "", "duration": "2h"})
        pin = self.tree.maintenance_entry("/ci/jobs")
        assert pin is not None
        self.client.post("/pins/maintenance", data={
            "path": "/ci/jobs", "action": "clear", "set_at": pin.token})
        (record,) = self.book.of("/ci/jobs")
        self.assertEqual((record.text, record.kind, record.ended, record.ended_by),
                         ("", MAINTENANCE, ENDED_HAND, "pan"))


class _Roots:
    """What a start asks of an engine: the configured checks' roots."""

    def __init__(self, *roots: str) -> None:
        self._roots = list(roots)

    def check_roots(self) -> list[str]:
        return self._roots


class StartRecordsEndsTests(TestCase):
    """Decision 4 at a start: the notes come back before the pins are replayed, so
    that a pin that ran out while the instance was down has its end in its note, at
    the time it ran out."""

    def setUp(self) -> None:
        self.addCleanup(setattr, app_module, "status_tree", app_module.status_tree)

    def test_a_pin_that_ran_out_while_down_has_its_end_in_its_note(self):
        ran_out = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
        pin = Pin(MAINTENANCE, "moving it", ran_out - timedelta(days=1), ran_out,
                  "ada")
        written = NoteBook()
        written.pinned("/site/db", "", pin, Context(code="error"))
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(app_module, "notes_book", NoteBook()) as book:
            state = StateLayer(directory)
            PinStore(state).save({"/site/db": pin})
            NoteStore(state).save(written.tables())
            app_module.status_tree = StatusTree()
            app_module._restore_state(_Roots("/site"), state)  # type: ignore[arg-type]
            (record,) = book.of("/site/db")
            self.assertEqual((record.text, record.ended, record.ended_at),
                             ("moving it", ENDED_CLOCK, ran_out))
            self.assertEqual(NoteStore(state).load()["/site/db"][0].ended,
                             ENDED_CLOCK, "and the file says so")
