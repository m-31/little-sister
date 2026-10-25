"""A node's notes (ADR-0047, ADR-0140): the book and its file, the retention that
retires a note, the pins that write one, and the surfaces that show them — the Notes
view, the line's way there, the Copy document's block and the page of a path no node
stands at."""
import json
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

from little_sister import app as app_module
from little_sister import instants, self_report
from little_sister.config import load_config
from little_sister.copy_status import NotesSaid, TimeStyle, format_node_markdown
from little_sister.engine import Engine
from little_sister.notes import (
    CONTEXT_LINES,
    Age,
    Context,
    ContextLine,
    Note,
    NoteBook,
    NoteStore,
    Retention,
    context_of,
    parse_age,
)
from little_sister.pins import MAINTENANCE, NO_NOTE, Pin
from little_sister.state import BACKUP_SUFFIX, NOTES_FILE, StateLayer
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import parse

BERLIN = ZoneInfo("Europe/Berlin")


def _utc(*moment: int) -> datetime:
    return datetime(*moment, tzinfo=UTC)


def _pin(note: str, created: datetime, *, by: str = "ada",
         set_at: datetime | None = None, set_by: str = "") -> Pin:
    return Pin(MAINTENANCE, note, set_at or created, created + timedelta(days=1),
                            set_by or by, created_at=created, created_by=by)


class ParseAgeTests(TestCase):
    """The two ages as the settings write them (ADR-0047 decision 10)."""

    def test_months_and_the_other_units(self):
        self.assertEqual(parse_age("13mo"), Age(months=13))
        self.assertEqual(parse_age(" 25 mo "), Age(months=25))
        self.assertEqual(parse_age("400d"), Age(seconds=400 * 86400))
        self.assertEqual(parse_age("8w"), Age(seconds=8 * 604800))
        self.assertEqual(parse_age("12h"), Age(seconds=12 * 3600))
        self.assertEqual(parse_age("30s"), Age(seconds=30))

    def test_a_bare_m_is_minutes_and_refused(self):
        with self.assertRaisesRegex(ValueError, "minutes.*mo"):
            parse_age("13m")
        with self.assertRaisesRegex(ValueError, "no age"):
            parse_age("13 months")
        with self.assertRaisesRegex(ValueError, "no age"):
            parse_age("")

    def test_a_month_is_the_calendars_in_the_zone(self):
        # thirteen months before the last of March is the last of February a
        # year back — the day clamped to the month — at the same hour in Berlin
        now = datetime(2026, 3, 31, 10, 0, tzinfo=BERLIN).astimezone(UTC)
        cutoff = Age(months=13).cutoff(now, BERLIN)
        self.assertEqual(cutoff.astimezone(BERLIN),
                         datetime(2025, 2, 28, 10, 0, tzinfo=BERLIN))
        self.assertEqual(cutoff.tzinfo, UTC)
        # and across a turn of the year
        self.assertEqual(Age(months=1).cutoff(_utc(2026, 1, 15, 12), BERLIN),
                         _utc(2025, 12, 15, 12))
        self.assertEqual(Age(seconds=3600).cutoff(_utc(2026, 1, 15, 12), BERLIN),
                         _utc(2026, 1, 15, 11))


class SettingsTests(TestCase):
    """The four keys in `settings.yaml` (ADR-0047 decision 11), each with its
    library default and a warning for a value it cannot use."""

    def _load(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text(text)
            return load_config(path)

    def test_the_defaults(self):
        cfg = self._load("timezone: UTC\n")
        self.assertEqual((cfg.notes_keep, cfg.notes_cap, cfg.notes_min_age,
                          cfg.notes_max_age), (10, 50, "13mo", "25mo"))
        self.assertEqual(cfg.notes_retention,
                         Retention(10, 50, Age(months=13), Age(months=25)))

    def test_written_values_are_read(self):
        cfg = self._load("notes_keep: 3\nnotes_cap: 7\nnotes_min_age: 400d\n"
                         "notes_max_age: 3mo\n")
        self.assertEqual(cfg.notes_retention,
                         Retention(3, 7, Age(seconds=400 * 86400), Age(months=3)))

    def test_a_value_it_cannot_use_warns_and_gives_way(self):
        for text, key, default in (("notes_keep: 0\n", "notes_keep", 10),
                                   ("notes_cap: many\n", "notes_cap", 50),
                                   ("notes_min_age: 13m\n", "notes_min_age", "13mo"),
                                   ("notes_max_age: soon\n", "notes_max_age", "25mo")):
            with self.subTest(text=text), self.assertLogs(level="WARNING") as said:
                self.assertEqual(getattr(self._load(text), key), default)
            self.assertTrue(any(key in line for line in said.output))


class BookTests(TestCase):
    """The history: appended to, newest first, and edited only as decision 5
    allows (ADR-0047)."""

    def setUp(self):
        self.book = NoteBook()

    def test_notes_are_listed_newest_first_and_counted(self):
        first = self.book.add("db", "", "one", by="ada", context=Context(),
                              now=_utc(2026, 1, 1))
        second = self.book.add("/db", "slow", "two", by="ben", context=Context(),
                               now=_utc(2026, 1, 2))
        self.assertEqual(self.book.of("/db"), (second, first))
        self.assertEqual(self.book.count("db"), 2)
        self.assertEqual(first.path, "/db")
        self.assertEqual((second.slug, second.created_by, second.set_by),
                         ("slow", "ben", "ben"))
        self.assertEqual(self.book.find("/db", first.key), first)
        self.assertIsNone(self.book.find("/db", "nothing"))
        self.assertEqual(self.book.of("/web"), ())

    def test_two_notes_at_one_instant_are_two(self):
        moment = _utc(2026, 1, 1)
        one = self.book.add("/db", "", "one", by="ada", context=Context(), now=moment)
        two = self.book.add("/db", "", "two", by="ada", context=Context(), now=moment)
        self.assertNotEqual(one.key, two.key)
        self.assertEqual(two.created_at, moment + timedelta(microseconds=1))
        self.assertEqual(self.book.of("/db"), (two, one))

    def test_beneath_takes_the_path_and_what_is_under_it(self):
        here = self.book.add("/a", "", "here", by="ada", context=Context(),
                             now=_utc(2026, 1, 1))
        under = self.book.add("/a/b", "", "under", by="ada", context=Context(),
                              now=_utc(2026, 1, 2))
        self.book.add("/ab", "", "beside", by="ada", context=Context(),
                      now=_utc(2026, 1, 3))
        self.assertEqual(self.book.beneath("/a"), (under, here))

    def test_an_edit_is_a_compare_and_set_on_the_newest_note_of_its_own(self):
        note = self.book.add("/db", "", "draft", by="ada", context=Context(),
                             now=_utc(2026, 1, 1))
        self.assertTrue(self.book.editable(note))
        done = self.book.edit("/db", note.key, "final", by="ben",
                              expected=note.token, now=_utc(2026, 1, 1, 1))
        self.assertTrue(done.applied)
        assert done.current is not None
        self.assertEqual((done.current.text, done.current.created_by,
                          done.current.set_by, done.current.created_at),
                         ("final", "ada", "ben", note.created_at))
        # the token it was drawn with is spent
        stale = self.book.edit("/db", note.key, "mine", by="cy", expected=note.token)
        self.assertTrue(stale.refused)
        self.assertEqual(stale.current, done.current)
        # saying what it says writes nothing and refuses nothing
        same = self.book.edit("/db", note.key, "final", by="cy",
                              expected=done.current.token)
        self.assertEqual((same.applied, same.refused), (False, False))

    def test_a_newer_note_freezes_the_one_before(self):
        old = self.book.add("/db", "", "old", by="ada", context=Context(),
                            now=_utc(2026, 1, 1))
        self.book.add("/db", "line", "newer", by="ben", context=Context(),
                      now=_utc(2026, 1, 2))
        self.assertFalse(self.book.editable(old))
        self.assertTrue(self.book.edit("/db", old.key, "x", by="ada",
                                       expected=old.token).refused)
        self.assertTrue(self.book.edit("/db", "gone", "x", by="ada",
                                       expected="").refused)

    def test_a_pins_note_enters_as_it_is_set_and_follows_its_pin(self):
        created = _utc(2026, 1, 1, 9)
        context = Context(code="error", lines=(ContextLine("slow", "error", "slow"),))
        note = self.book.pinned("db", "", _pin("rebooting", created), context)
        assert note is not None
        self.assertEqual((note.text, note.pin, note.created_at, note.context),
                         ("rebooting", instants.stamp(created), created, context))
        # an edit of the pin while it stands changes its note, not the history
        edited = _pin("rebooting, back at ten", created, set_at=_utc(2026, 1, 1, 10),
                      set_by="ben")
        again = self.book.pinned("/db", "", edited, Context(code="maintenance"))
        assert again is not None
        self.assertEqual((again.text, again.set_by, again.created_by, again.context),
                         ("rebooting, back at ten", "ben", "ada", context))
        self.assertEqual(self.book.count("/db"), 1)
        # a pin's note is changed with its pin and never on its own
        self.assertFalse(self.book.editable(again))
        self.assertTrue(self.book.edit("/db", again.key, "x", by="ada",
                                       expected=again.token).refused)
        # a new pin is a new note, beside the one the ended pin left
        later = self.book.pinned("/db", "", _pin("rebooting", _utc(2026, 2, 1)),
                                 Context())
        assert later is not None
        self.assertEqual(self.book.of("/db"), (later, again))

    def test_a_pin_without_a_note_writes_none(self):
        self.assertIsNone(self.book.pinned("/db", "", _pin(NO_NOTE, _utc(2026, 1, 1)),
                                           Context()))
        self.assertEqual(self.book.count("/db"), 0)
        # and one given its note by an edit writes it then
        created = _utc(2026, 1, 1)
        given = _pin("now with words", created, set_at=_utc(2026, 1, 2), set_by="ben")
        note = self.book.pinned("/db", "", given, Context())
        assert note is not None
        self.assertEqual((note.created_at, note.created_by), (_utc(2026, 1, 2), "ben"))

    def test_a_lines_pin_and_the_nodes_keep_notes_apart(self):
        created = _utc(2026, 1, 1)
        node = self.book.pinned("/db", "", _pin("whole box", created), Context())
        line = self.book.pinned("/db", "slow", _pin("this one", created), Context())
        assert node is not None and line is not None
        self.assertNotEqual(node.key, line.key)
        self.assertEqual({note.slug for note in self.book.of("/db")}, {"", "slow"})


class RetentionTests(TestCase):
    """Decision 9: retired if and only if not among the last `notes_keep` on its
    node, and either older than `notes_max_age`, or the node holds more than
    `notes_cap` and it is older than `notes_min_age`."""

    NOW = _utc(2026, 10, 1, 12)

    def _book(self, ages_in_days: list[int], path: str = "/db") -> NoteBook:
        book = NoteBook()
        for number, days in enumerate(ages_in_days):
            book.add(path, "", f"note {number}", by="ada", context=Context(),
                     now=self.NOW - timedelta(days=days))
        return book

    def _texts(self, book: NoteBook, path: str = "/db") -> list[str]:
        return [note.text for note in reversed(book.of(path))]

    def test_the_count_floor_wins_over_every_age(self):
        book = self._book([1500, 1400, 1300])
        retention = Retention(keep=3, cap=1, min_age=Age(seconds=1),
                              max_age=Age(seconds=1))
        self.assertEqual(book.retire(retention, now=self.NOW, zone=BERLIN), 0)
        self.assertEqual(len(book.of("/db")), 3)

    def test_past_the_ceiling_a_note_goes_by_its_age_alone(self):
        # twenty-five months is some 760 days: the first is past it, the second not
        book = self._book([900, 700, 10, 5])
        retention = Retention(keep=1, cap=50, min_age=Age(months=13),
                              max_age=Age(months=25))
        self.assertEqual(book.retire(retention, now=self.NOW, zone=BERLIN), 1)
        self.assertEqual(self._texts(book), ["note 1", "note 2", "note 3"])

    def test_the_cap_trims_the_oldest_past_the_floor_down_to_the_cap(self):
        # five notes, a cap of two: the three oldest are over it, and of those only
        # the two past the floor may go — never below it
        book = self._book([500, 450, 100, 50, 10])
        retention = Retention(keep=1, cap=2, min_age=Age(seconds=400 * 86400),
                              max_age=Age(months=25))
        self.assertEqual(book.retire(retention, now=self.NOW, zone=BERLIN), 2)
        self.assertEqual(self._texts(book), ["note 2", "note 3", "note 4"])

    def test_the_cap_stops_once_the_node_is_down_to_it(self):
        book = self._book([500, 450, 420, 10])
        retention = Retention(keep=1, cap=3, min_age=Age(seconds=400 * 86400),
                              max_age=Age(months=25))
        self.assertEqual(book.retire(retention, now=self.NOW, zone=BERLIN), 1)
        self.assertEqual(self._texts(book), ["note 1", "note 2", "note 3"])

    def test_a_node_whose_every_note_is_retired_is_gone_from_the_book(self):
        book = self._book([900])
        retention = Retention(keep=0, cap=50, min_age=Age(months=13),
                              max_age=Age(months=25))
        self.assertEqual(book.retire(retention, now=self.NOW, zone=BERLIN), 1)
        self.assertEqual(book.tables(), {})

    def test_each_node_is_its_own(self):
        book = self._book([900, 900])
        for days in (900, 900, 900):
            book.add("/web", "", "web", by="ada", context=Context(),
                     now=self.NOW - timedelta(days=days))
        retention = Retention(keep=2, cap=50, min_age=Age(months=13),
                              max_age=Age(months=25))
        self.assertEqual(book.retire(retention, now=self.NOW, zone=BERLIN), 1)
        self.assertEqual((book.count("/db"), book.count("/web")), (2, 2))


class StoreTests(TestCase):
    """`var/state/notes.json`: plain JSON, written through by every change, read at
    the start and adopted at a takeover (ADR-0071, ADR-0077)."""

    def test_every_change_is_written_through_and_read_back(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            book = NoteBook()
            store = NoteStore(state)
            book.use_store(store)
            context = Context(code="error", lines=(ContextLine("a", "warn", "x"),),
                              more=3)
            note = book.add("/db", "a", "**found it**", by="ada", context=context,
                            now=_utc(2026, 1, 1))
            book.pinned("/db", "", _pin("pinned", _utc(2026, 1, 2)), Context())
            written = json.loads(state.path(NOTES_FILE).read_text())
            self.assertEqual(len(written["notes"]["/db"]), 2)
            self.assertEqual(written["notes"]["/db"][0]["text"], "**found it**")
            self.assertEqual(written["notes"]["/db"][0]["created_at"],
                             instants.stamp(note.created_at))
            self.assertEqual(store.load(), book.tables())
            edited = book.edit("/db", book.of("/db")[0].key, "x", by="ben",
                               expected="nope")
            self.assertTrue(edited.refused)
            self.assertEqual(store.load(), book.tables())

    def test_a_file_it_cannot_take_is_a_load_failure_and_starts_empty(self):
        for payload in ([1, 2], {"notes": []}, {"notes": {"/db": {}}},
                        {"notes": {"/db": [{"text": "x",
                                            "created_at": "2026-01-01T00:00:00"}]}}):
            with self.subTest(payload=payload), \
                    tempfile.TemporaryDirectory() as directory:
                state = StateLayer(directory)
                state.path(NOTES_FILE).write_text(json.dumps(payload))
                with self.assertLogs(level="ERROR"):
                    self.assertEqual(NoteStore(state).load(), {})
                self.assertEqual([line.slug for line in state.lines()],
                                 [f"load.{NOTES_FILE}"])

    def test_no_file_is_no_note(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(NoteStore(StateLayer(directory)).load(), {})

    def test_an_adopted_copy_replaces_the_history(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            book = NoteBook()
            store = NoteStore(state, book=book)
            book.use_store(store)
            book.add("/mine", "", "mine", by="ada", context=Context(),
                     now=_utc(2026, 1, 1))
            other = NoteBook()
            theirs = other.add("/theirs", "", "theirs", by="ben", context=Context(),
                               now=_utc(2026, 1, 2))
            state.path(NOTES_FILE + BACKUP_SUFFIX).write_text(json.dumps(
                {"notes": {"/theirs": [theirs.to_dict()]}}))
            state.take_stock()
            state.take_backups()
            self.assertEqual(book.of("/theirs"), (theirs,))
            self.assertEqual(book.of("/mine"), ())

    def test_a_note_round_trips_whole(self):
        note = Note(path="/db", slug="a", text="x", created_at=_utc(2026, 1, 1),
                    created_by="ada", set_at=_utc(2026, 1, 2), set_by="ben",
                    pin=instants.stamp(_utc(2026, 1, 1)),
                    context=Context(code="ok", lines=(ContextLine("a", "", "y"),),
                                    more=1))
        self.assertEqual(Note.from_dict("/db", note.to_dict()), note)
        # a note of the node's own carries no slug and no pin in its file
        plain = Note(path="/db", slug="", text="x", created_at=_utc(2026, 1, 1),
                     created_by="ada", set_at=_utc(2026, 1, 1), set_by="ada")
        self.assertNotIn("slug", plain.to_dict())
        self.assertNotIn("pin", plain.to_dict())
        self.assertEqual(Note.from_dict("/db", plain.to_dict()), plain)


class ContextTests(TestCase):
    """Decision 6: the node's status and its lines as they stood."""

    def test_a_nodes_note_takes_its_lines_and_a_lines_note_its_line(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, {"slow": "queries slow",
                                              "disk": "disk at 91%"})
        node = tree.snapshot("/db")
        self.assertEqual(context_of(node), Context(
            code="error", lines=(ContextLine("slow", "", "queries slow"),
                                 ContextLine("disk", "", "disk at 91%"))))
        self.assertEqual(context_of(node, "disk"), Context(
            code="error", lines=(ContextLine("disk", "", "disk at 91%"),)))
        self.assertEqual(context_of(node, "nothing"), Context(code="error"))
        self.assertEqual(context_of(None), Context())

    def test_the_lines_are_capped_and_the_rest_counted(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.WARN,
                    {f"l{number}": f"line {number}" for number in range(60)})
        said = context_of(tree.snapshot("/db"))
        self.assertEqual((len(said.lines), said.more), (CONTEXT_LINES, 10))


class _Web(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.book = NoteBook()
        patcher = mock.patch.object(app_module, "notes_book", self.book)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app_module.app.test_client()
        self.tree.upsert("/db", StatusCode.ERROR,
                         {"slow": "queries are slow", "disk": "disk at 91%"},
                         members=True)

    def _login(self) -> None:
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _viewer(self) -> None:
        with self.client.session_transaction() as session:
            session["username"] = "viewer"
            session["firstname"] = "Vera"
            session["admin"] = False

    def _page(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def _pin(self, **fields: str):
        return self.client.post("/pins/maintenance", data={
            "path": "db", "action": "set", "duration": "2h", **fields})


class PinsWriteNotesTests(_Web):
    """A pin's note enters the node's notes as the pin is set (ADR-0047 decision 4)
    and follows its edits while it stands (decision 5)."""

    def test_a_pin_set_with_a_note_writes_it_with_what_the_node_showed(self):
        self._login()
        self._pin(note="rotating the logs")
        (note,) = self.book.of("/db")
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual((note.text, note.pin, note.created_by),
                         ("rotating the logs", instants.stamp(entry.created_at),
                          "pan"))
        # what it showed before the pin, not the pin's maintenance
        self.assertEqual(note.context.code, "error")
        self.assertEqual([line.slug for line in note.context.lines],
                         ["slow", "disk"])

    def test_an_edit_follows_and_a_clear_leaves_the_note(self):
        self._login()
        self._pin(note="rotating the logs")
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self._pin(note="rotating the logs, then a reboot", set_at=entry.token)
        (note,) = self.book.of("/db")
        self.assertEqual(note.text, "rotating the logs, then a reboot")
        now = self.tree.maintenance_entry("/db")
        assert now is not None
        self.client.post("/pins/maintenance", data={"path": "db", "action": "clear",
                                                "set_at": now.token})
        self.assertIsNone(self.tree.maintenance_entry("/db"))
        self.assertEqual(self.book.of("/db"), (note,))

    def test_a_pin_without_a_note_and_a_refused_pin_write_none(self):
        self._login()
        self._pin(note="")
        self.assertEqual(self.book.of("/db"), ())
        refused = self._pin(note="mine", set_at="2020-01-01T00:00:00Z")
        self.assertEqual(refused.status_code, 200)
        self.assertEqual(self.book.of("/db"), ())

    def test_a_lines_pin_writes_the_lines_note(self):
        self._login()
        self._pin(slug="slow", note="an index is missing")
        (note,) = self.book.of("/db")
        self.assertEqual((note.slug, [line.slug for line in note.context.lines]),
                         ("slow", ["slow"]))


class NotesViewTests(_Web):
    """The Notes view (ADR-0140): a tab after History, its count beside it, every
    note newest first, and an admin's add and edit."""

    def test_the_tab_stands_after_history_with_its_count_and_not_on_the_root(self):
        self._login()
        self.book.add("/db", "", "one", by="ada", context=Context())
        self.book.add("/db", "slow", "two", by="ada", context=Context())
        tabs = parse(self._page("/status/db")).one("ls-views")
        labels = [tab.text() for tab in tabs.all("ls-views__tab")]
        self.assertEqual(labels[1:3], ["History", "Notes 2 notes"])
        root = parse(self._page("/status")).one("ls-views")
        self.assertNotIn("Notes", root.text())
        self.tree.upsert("/web", StatusCode.OK)
        self.assertIn("Notes</a>", self._page("/status/web"))

    def test_notes_are_listed_newest_first_with_their_authors_and_line(self):
        self._login()
        self.book.add("/db", "", "the **node**", by="ada", context=Context(code="ok"),
                      now=_utc(2026, 1, 1))
        self.book.add("/db", "slow", "the line", by="ben",
                      context=context_of(self.tree.snapshot("/db"), "slow"),
                      now=_utc(2026, 1, 2))
        page = parse(self._page("/notes/db"))
        notes = page.all("ls-note")
        self.assertEqual([note.one("ls-note__text").text() for note in notes],
                         ["the line", "the node"])
        said = notes[0].one("ls-note__said").text()
        self.assertIn("On a line: queries are slow.", said)
        self.assertIn("Written by ben", said)
        self.assertIn("<strong>node</strong>", self._page("/notes/db"))
        link = notes[0].one("ls-note__said").one(tag="a")
        self.assertEqual(link.attrs["href"], "/status/db?reason=slow#pinned-reason")
        self.assertEqual(notes[1].one("ls-note__said").text().split(" Written")[0],
                         "On the node.")
        # what the line read then, folded
        context = notes[0].one("ls-note__context")
        self.assertEqual(context.tag, "details")
        self.assertIn("The node showed error", context.text())

    def test_what_the_node_showed_has_a_status_column_where_a_line_declares_one(
            self):
        self._login()
        plain = Context(code="error", lines=(ContextLine("a", "", "one"),
                                             ContextLine("b", "", "two")))
        coded = Context(code="error", lines=(ContextLine("a", "warn", "one"),
                                             ContextLine("b", "", "two")), more=3)
        self.book.add("/db", "", "plain", by="ada", now=_utc(2026, 1, 1), context=plain)
        self.book.add("/db", "", "coded", by="ada", now=_utc(2026, 1, 2), context=coded)
        page = parse(self._page("/notes/db"))
        coded, plain = page.all("ls-note__lines")
        rows = coded.all(tag="tr")
        self.assertEqual([len(row.all(tag="td")) for row in rows], [2, 2])
        self.assertTrue(rows[0].has("row-warn"))
        self.assertEqual(rows[0].all(tag="td")[0].text(), "warn")
        self.assertEqual([len(row.all(tag="td")) for row in plain.all(tag="tr")],
                         [1, 1])
        self.assertIn("And 3 more lines.", page.all("ls-note__context")[0].text())

    def test_a_note_on_a_line_the_run_does_not_report_is_marked(self):
        # decision 8: absence suspends, it does not delete
        self._login()
        self.book.add("/db", "gone", "about a line", by="ada", context=Context(
            code="warn", lines=(ContextLine("gone", "warn", "a line once"),)))
        said = parse(self._page("/notes/db")).one("ls-note__said")
        self.assertIn("On a line: a line once", said.text())
        self.assertIn("the check does not report it now", said.text())
        self.assertEqual(said.all(tag="a"), [])

    def test_a_pins_note_says_whether_its_pin_stands(self):
        self._login()
        self._pin(note="rotating the logs")
        said = parse(self._page("/notes/db")).one("ls-note__said").text()
        self.assertIn("The note of a pin that stands, and changed with it.", said)
        self.assertEqual(parse(self._page("/notes/db")).all("ls-note__edit"), [])
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.client.post("/pins/maintenance", data={"path": "db", "action": "clear",
                                                "set_at": entry.token})
        said = parse(self._page("/notes/db")).one("ls-note__said").text()
        self.assertIn("The note of a pin that has ended.", said)
        # a pin set since is another pin: the note it names is its own
        self._pin(note="rebooting")
        said = [box.text()
                for box in parse(self._page("/notes/db")).all("ls-note__said")]
        self.assertIn("The note of a pin that stands, and changed with it.", said[0])
        self.assertIn("The note of a pin that has ended.", said[1])

    def test_an_admin_adds_a_note_on_the_node_or_a_line(self):
        self._login()
        page = parse(self._page("/notes/db?reason=disk"))
        add = page.with_id("add-note")
        self.assertIn("open", add.attrs)
        options = {box.attrs["value"]: "selected" in box.attrs
                   for box in add.all(tag="option")}
        self.assertEqual(options, {"": False, "slow": False, "disk": True})
        response = self.client.post("/notes/db", data={
            "action": "add", "slug": "disk", "text": "grows 2% a week"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/notes/db")
        (note,) = self.book.of("/db")
        self.assertEqual((note.slug, note.text, note.created_by, note.pin),
                         ("disk", "grows 2% a week", "pan", ""))
        self.assertEqual(note.context.lines, (ContextLine("disk", "", "disk at 91%"),))
        self.assertIn("Notes <span class=\"ls-views__count\">1</span>",
                      self._page("/status/db"))

    def test_a_note_without_words_is_refused(self):
        self._login()
        response = self.client.post("/notes/db", data={"action": "add",
                                                       "slug": "slow", "text": "  "})
        self.assertEqual(response.status_code, 200)
        page = parse(response.get_data(as_text=True))
        self.assertIn("A note needs words", page.one("ls-notes__refused").text())
        self.assertEqual(self.book.of("/db"), ())

    def test_the_newest_note_of_its_own_is_edited_and_a_stale_edit_refused(self):
        self._login()
        older = self.book.add("/db", "", "older", by="ada", context=Context(),
                              now=_utc(2026, 1, 1))
        note = self.book.add("/db", "", "draft", by="ada", context=Context(),
                             now=_utc(2026, 1, 2))
        page = parse(self._page("/notes/db"))
        (editor,) = page.all("ls-note__edit")
        fields = {box.attrs["name"]: box.attrs.get("value", "")
                  for box in editor.all(tag="input")}
        self.assertEqual(fields, {"action": "edit", "key": note.key,
                                  "set_at": note.token})
        saved = self.client.post("/notes/db", data={**fields, "text": "final"})
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(self.book.of("/db")[0].text, "final")
        # the same form again: somebody changed it since
        stale = self.client.post("/notes/db", data={**fields, "text": "mine"})
        self.assertEqual(stale.status_code, 200)
        page = parse(stale.get_data(as_text=True))
        self.assertIn("Somebody changed this note",
                      page.one("ls-notes__refused").text())
        editor = page.one("ls-note__edit")
        self.assertIn("open", editor.attrs)
        self.assertEqual(editor.one(tag="textarea").source(), "mine")
        token = [box.attrs["value"] for box in editor.all(tag="input")
                 if box.attrs["name"] == "set_at"]
        self.assertEqual(token, [self.book.of("/db")[0].token])
        # and the older one is no longer the newest: it may not be changed
        refused = self.client.post("/notes/db", data={
            "action": "edit", "key": older.key, "set_at": older.token,
            "text": "rewritten"})
        page = parse(refused.get_data(as_text=True))
        self.assertIn("A newer note was written", page.one("ls-notes__refused").text())
        self.assertEqual(page.with_id("note-text").source(), "rewritten")
        self.assertEqual(self.book.find("/db", older.key), older)

    def test_a_reader_sees_the_notes_and_no_form(self):
        self._viewer()
        self.book.add("/db", "", "kept", by="ada", context=Context())
        page = parse(self._page("/notes/db"))
        self.assertEqual(page.all("ls-notes__add"), [])
        self.assertEqual(page.all("ls-note__edit"), [])
        self.assertEqual(self.client.post("/notes/db", data={
            "action": "add", "text": "x"}).status_code, 403)

    def test_a_line_leads_to_its_note(self):
        self._login()
        page = parse(self._page("/status/db"))
        links = [box.one(tag="a").attrs["href"]
                 for box in page.all("rule-block__notes")]
        self.assertIn("/notes/db?reason=slow#add-note", links)

    def test_the_view_needs_a_sign_in_and_a_node(self):
        self.assertNotEqual(self.client.get("/notes/db").status_code, 200)
        self._login()
        self.assertEqual(self.client.get("/notes/nothing/here").status_code, 404)


class GonePathTests(_Web):
    """Decision 7: the notes outlive the node, and the page of a path no node stands
    at lists the ones written for it and beneath it (ADR-0116, ADR-0140)."""

    def test_the_page_lists_the_notes_for_the_path_and_beneath_it(self):
        self._login()
        self.book.add("/gone", "", "the box was retired", by="ada",
                      context=Context(code="error"), now=_utc(2026, 1, 1))
        self.book.add("/gone/disk", "", "replaced", by="ben", context=Context(),
                      now=_utc(2026, 1, 2))
        for url in ("/status/gone", "/notes/gone", "/history/gone"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                page = parse(response.get_data(as_text=True))
                section = page.one("ls-no-node__notes")
                notes = section.all("ls-note")
                self.assertEqual([note.one("ls-note__text").text() for note in notes],
                                 ["replaced", "the box was retired"])
                self.assertIn("At /gone/disk.", notes[0].one("ls-note__said").text())
                self.assertNotIn("At ", notes[1].one("ls-note__said").text())
                self.assertEqual(section.all("ls-note__edit"), [])
                self.assertIn("2 notes are kept for it and beneath it",
                              section.text())


class CopyNotesTests(TestCase):
    """The Copy document's *Notes* block, after the node's reasons (ADR-0140)."""

    def setUp(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, {"slow": "queries are slow"})
        self.node = tree.snapshot("/db")
        self.style = TimeStyle(UTC, "%Y-%m-%d %H:%M")

    def test_the_newest_note_whole_and_how_many_more(self):
        note = Note(path="/db", slug="slow", text="An index is missing.\n\nSee T-1.",
                    created_at=_utc(2026, 1, 1, 9), created_by="ada",
                    set_at=_utc(2026, 1, 2, 9), set_by="ben",
                    pin=instants.stamp(_utc(2026, 1, 1, 9)),
                    context=Context(code="error",
                                    lines=(ContextLine("slow", "", "queries slow"),)))
        document = format_node_markdown(
            self.node, self.style, notes=NotesSaid(note, 2, "https://x/notes/db"))
        block = document.split("**Notes**", 1)[1]
        self.assertLess(document.index("**Reasons**"), document.index("**Notes**"))
        self.assertIn("- By ada, 2026-01-01 09:00 +00:00; last changed by ben, "
                      "2026-01-02 09:00 +00:00 — the note of a pin — on its line: "
                      "queries slow", block)
        self.assertIn("  - An index is missing.\n    \n    See T-1.", block)
        self.assertIn("- 2 more on its Notes view: https://x/notes/db", block)

    def test_no_note_no_block(self):
        self.assertNotIn("**Notes**", format_node_markdown(self.node, self.style))

    def test_a_branch_carries_it_before_what_is_beneath_it(self):
        tree = StatusTree()
        tree.upsert("/host", StatusCode.WARN, "own")
        tree.upsert("/host/disk", StatusCode.ERROR, "full")
        note = Note(path="/host", slug="", text="new disks on order",
                    created_at=_utc(2026, 1, 1), created_by="ada",
                    set_at=_utc(2026, 1, 1), set_by="ada")
        document = format_node_markdown(tree.snapshot("/host"), self.style,
                                        notes=NotesSaid(note))
        self.assertLess(document.index("**Notes**"), document.index("**Beneath it**"))
        self.assertNotIn("more on its Notes view", document)

    def test_the_copy_page_carries_the_block(self):
        app_module.app.config["TESTING"] = True
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, {"slow": "queries are slow"})
        book = NoteBook()
        book.add("/db", "", "older", by="ada", context=Context(), now=_utc(2026, 1, 1))
        book.add("/db", "", "newest", by="ada", context=Context(), now=_utc(2026, 1, 2))
        client = app_module.app.test_client()
        with mock.patch.object(app_module, "status_tree", tree), \
                mock.patch.object(app_module, "notes_book", book):
            client.post("/login", data={"username": "pan", "password": "12345678"})
            body = client.get("/copy/db").get_data(as_text=True)
        self.assertIn("newest", body)
        self.assertNotIn("older", body)
        self.assertIn("1 more on its Notes view: http://localhost/notes/db", body)


class StartTests(TestCase):
    """The start reads the file, writes through it, and retires on the tick
    (ADR-0047 decision 12)."""

    def test_the_start_restores_and_registers_the_retention(self):
        book = NoteBook()
        old = book.add("/db", "", "kept a long time", by="ada", context=Context(),
                       now=datetime.now(UTC) - timedelta(days=2000))
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(app_module, "notes_book", NoteBook()) as started:
            state = StateLayer(directory)
            NoteStore(state).save(book.tables())
            engine = Engine([], StatusTree())
            app_module._restore_notes(engine, state)
            self.assertEqual(started.of("/db"), (old,))
            # written through from now on
            started.add("/web", "", "new", by="ben", context=Context())
            self.assertEqual(set(NoteStore(state).load()), {"/db", "/web"})
            # and the tick retires what the retention says is past keeping
            config = mock.patch.object(app_module, "config", mock.Mock(
                notes_retention=Retention(keep=0, cap=50, min_age=Age(months=13),
                                          max_age=Age(months=25)),
                tzinfo=BERLIN))
            with config:
                engine._publish(time.monotonic())
            self.assertEqual(started.of("/db"), ())
            self.assertEqual(set(NoteStore(state).load()), {"/web"})

    def test_a_sweep_that_raises_is_a_line_and_the_tick_goes_on(self):
        engine = Engine([], StatusTree())
        ran: list[str] = []

        def boom() -> None:
            raise RuntimeError("no")
        engine.every_tick("notes", boom)
        engine.every_tick("after", lambda: ran.append("after"))
        with self.assertLogs(level="ERROR"):
            engine._publish(time.monotonic())
        self.assertEqual(ran, ["after"])
        self.assertIn("notes.sweep",
                      {line.slug for line in self_report.runtime.lines()})
