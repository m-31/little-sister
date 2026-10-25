"""What a Copy document hands over (ADR-0115): where it is from, when it was made,
since when each finding has stood, and for a branch what is beneath it.

``tests/test_copy_status.py`` holds what the documents carried before — the outline,
a leaf's facts, a line's — and still do. These are written from the record's
sentences: the two lines every document gains, the instant on each finding, what a
branch's line in an outline says of the branch itself, the head of the tree's
document, a branch's document, and the period of a node nothing has written — and
ADR-0133's: the *Handbook* line of a node that has one, and a link a text writes in
the short form written out to its node's handbook. The last class asks the routes,
since the addresses and the periods are theirs to supply.

What a browser has to show — that *Copy Rich HTML* puts both members on the clipboard,
also over plain http — is ``tests/test_copy_browser.py``'s, and the page as a view of
its node, in the node's band, ``tests/test_copy_tab.py``'s.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.copy_status import (
    Origin,
    TimeStyle,
    format_copy_markdown,
    format_node_markdown,
    format_reason_markdown,
    format_tree_markdown,
)
from little_sister.reasons import Entry
from little_sister.render import render_markdown
from little_sister.status import StatusCode
from little_sister.tree import StatusSnapshot, StatusTree
from tests.page_tree import parse

BERLIN = TimeStyle(ZoneInfo("Europe/Berlin"))
OK, WARN, ERROR, UNDEFINED = (StatusCode.OK, StatusCode.WARN, StatusCode.ERROR,
                              StatusCode.UNDEFINED)


def _utc(*moment: int) -> datetime:
    """An instant, by its date and its time in UTC."""
    return datetime(*moment, tzinfo=UTC)


#: An instant in January, one hour off UTC in Berlin, and what the documents write.
MADE = _utc(2026, 1, 15, 9, 0)
AS_OF = "2026-01-15 10:00:00 +01:00"
SITE = "https://sister.example.org"
SOON = datetime.now(UTC) + timedelta(days=2)


def origin(path: str = "") -> Origin:
    return Origin(f"{SITE}/status{path}", MADE)


def handbooks(path: str) -> str:
    """A node's handbook as a route addresses it, absolute (ADR-0133 decision 3):
    the root's at `/handbook`."""
    return f"{SITE}/handbook{path.rstrip('/')}"


def addressed(path: str = "") -> Origin:
    """An origin that says where each node's handbook is, as the routes' does."""
    return Origin(f"{SITE}/status{path}", MADE, handbooks=handbooks)


@dataclass(frozen=True)
class Stood:
    """A period's beginning as a route hands it over."""
    at: str
    before: bool = False
    began: str = ""


def periods(**by_name: Stood):
    """What the tree knows of each node's period, by the node's name."""
    return lambda node: by_name.get(node.name)


def lines(document: str) -> list[str]:
    return document.split("\n")


class _Tree(TestCase):
    def setUp(self) -> None:
        self.tree = StatusTree(root_name="Production")

    def node(self, path: str) -> StatusSnapshot:
        found = self.tree.snapshot(path)
        assert found is not None, path
        return found

    def root(self) -> StatusSnapshot:
        return self.node("")

    def host(self, name: str = "nexus", disk: StatusCode = ERROR) -> None:
        """A host as a check that grades its children writes it: nothing of its
        own, and three nodes beneath it."""
        self.tree.upsert(f"/{name}", UNDEFINED, None, frequency_seconds=120,
                         report="- **Uptime:** 83d", config="- **host:** nexus")
        self.tree.upsert(f"/{name}/cpu", OK, "9 % busy")
        self.tree.upsert(f"/{name}/disk", disk,
                         "97 % used" if disk is not OK else "61 % used")
        self.tree.upsert(f"/{name}/memory", WARN if disk is not OK else OK,
                         "88 % used" if disk is not OK else "38 % used")


class WhereAndWhenTests(_Tree):
    """Decision 1: the address of the page a document was made from, and the instant
    it was made, in every document."""

    def test_a_nodes_document_carries_them_beneath_its_path(self):
        self.tree.upsert("/services/api", ERROR, "down")
        document = format_node_markdown(self.node("services/api"), BERLIN,
                                        origin=origin("/services/api"))
        self.assertEqual(lines(document)[:6], [
            "## api ⛔",
            "",
            "- **Path:** /services/api",
            f"- **Dashboard:** {SITE}/status/services/api",
            f"- **As of:** {AS_OF}",
            "- **Reported:** error ⛔",
        ])

    def test_a_lines_document_carries_them_too(self):
        self.tree.upsert("/ci/reviews", WARN, {"pr-1": "PR one waits"}, members=True)
        node = replace(self.node("ci/reviews"), timestamp=_utc(2026, 1, 15, 8, 59))
        document = format_reason_markdown(
            node, node.reasons[0], BERLIN,
            origin=Origin(f"{SITE}/status/ci/reviews?reason=pr-1", MADE))
        self.assertEqual(lines(document)[:7], [
            "## reviews ⚠️",
            "",
            "- **Path:** /ci/reviews",
            f"- **Dashboard:** {SITE}/status/ci/reviews?reason=pr-1",
            f"- **As of:** {AS_OF}",
            "- **Observed:** 2026-01-15 09:59:00 +01:00",
            "",
        ])

    def test_the_instant_is_written_in_the_documents_clock(self):
        # the same instant in August stands two hours off UTC, and says so
        self.tree.upsert("/services/api", ERROR, "down")
        document = format_node_markdown(
            self.node("services/api"), BERLIN,
            origin=Origin(f"{SITE}/status/services/api", _utc(2026, 8, 15, 9, 0)))
        self.assertIn("- **As of:** 2026-08-15 11:00:00 +02:00", lines(document))

    def test_the_address_is_a_link_in_the_rich_form(self):
        self.tree.upsert("/services/api", ERROR, "down")
        document = format_node_markdown(self.node("services/api"), BERLIN,
                                        origin=origin("/services/api"))
        rich = parse(str(render_markdown(document)))
        link, = rich.all(tag="a")
        self.assertEqual(link.attrs["href"], f"{SITE}/status/services/api")
        self.assertEqual(link.text(), f"{SITE}/status/services/api")

    def test_a_caller_with_no_request_claims_no_address_and_no_instant(self):
        self.tree.upsert("/ci/reviews", WARN, {"pr-1": "PR one waits"}, members=True)
        node = self.node("ci/reviews")
        for document in (format_node_markdown(node, BERLIN),
                         format_reason_markdown(node, node.reasons[0], BERLIN)):
            self.assertNotIn("Dashboard", document)
            self.assertNotIn("As of", document)


class HandbookTests(_Tree):
    """ADR-0133 decisions 3 and 4: a node that has a handbook names it beside its
    page, and a link any text of the document writes in the short form leaves the
    instance written out to the handbook of the node the text belongs to."""

    LED = "[what to do](handbook#when-it-fails)"

    def test_a_node_and_a_line_name_the_handbook_beside_the_page(self):
        self.tree.upsert("/ci/reviews", WARN, {"pr-1": "PR one waits"}, members=True)
        self.tree.set_handbook("/ci/reviews", "## When it fails\n")
        node = self.node("ci/reviews")
        for document in (
                format_node_markdown(node, BERLIN, origin=addressed("/ci/reviews")),
                format_reason_markdown(node, node.reasons[0], BERLIN,
                                       origin=addressed("/ci/reviews"))):
            with self.subTest(document=document[:40]):
                said = lines(document)
                dashboard = said.index(f"- **Dashboard:** {SITE}/status/ci/reviews")
                self.assertEqual(said[dashboard + 1:dashboard + 3], [
                    f"- **Handbook:** {SITE}/handbook/ci/reviews",
                    f"- **As of:** {AS_OF}"])

    def test_one_without_names_none_and_so_does_a_caller_that_cannot_say(self):
        self.tree.upsert("/ci/reviews", WARN, "waits")
        self.assertNotIn("Handbook", format_node_markdown(
            self.node("ci/reviews"), BERLIN, origin=addressed("/ci/reviews")))
        self.tree.set_handbook("/ci/reviews", "## When it fails\n")
        self.assertNotIn("Handbook", format_node_markdown(
            self.node("ci/reviews"), BERLIN, origin=origin("/ci/reviews")))

    def test_a_branch_and_the_tree_name_theirs(self):
        self.host()
        self.tree.set_handbook("/nexus", "## Sign in\n")
        self.tree.set_handbook("", "## Whom to call\n")
        self.assertIn(f"- **Handbook:** {SITE}/handbook/nexus",
                      lines(format_node_markdown(self.node("nexus"), BERLIN,
                                                 origin=addressed("/nexus"))))
        self.assertIn(f"- **Handbook:** {SITE}/handbook",
                      lines(format_tree_markdown(self.root(), BERLIN, addressed())))

    def test_every_text_writes_the_short_form_out_to_its_own_nodes_handbook(self):
        self.tree.upsert("/svc/api", ERROR, f"503 — {self.LED}",
                         report=f"- {self.LED}", config=f"- **url:** {self.LED}")
        self.tree.set_title("/svc/api", "Gateway [runbook](handbook)")
        self.tree.set_maintenance("/svc/api", f"deploying — {self.LED}",
                                  set_by="lex", expires_at=SOON)
        node_document = format_node_markdown(self.node("svc/api"), BERLIN,
                                             origin=addressed("/svc/api"))
        led = f"[what to do]({SITE}/handbook/svc/api#when-it-fails)"
        self.assertEqual(node_document.count(led), 4)
        self.assertIn(f"Gateway [runbook]({SITE}/handbook/svc/api)", node_document)
        self.assertNotIn("](handbook", node_document)
        # the tree's outline writes each node's out to its own node's handbook
        self.tree.upsert("/svc/db", ERROR, "[restore it](handbook#restore)")
        tree_document = format_tree_markdown(self.root(), BERLIN, addressed())
        self.assertIn(led, tree_document)
        self.assertIn(f"[restore it]({SITE}/handbook/svc/db#restore)", tree_document)
        self.assertNotIn("](handbook", tree_document)

    def test_without_the_addresses_the_short_form_stays_as_written(self):
        self.tree.upsert("/svc/api", ERROR, self.LED)
        self.assertIn(self.LED, format_node_markdown(self.node("svc/api"), BERLIN,
                                                     origin=origin("/svc/api")))


class SinceWhenTests(_Tree):
    """Decision 2: a listed node says the status it shows and since when."""

    def outline(self, **stood: Stood) -> list[str]:
        return lines(format_copy_markdown(self.root(), BERLIN,
                                          periods=periods(**stood)))

    def test_a_finding_says_the_status_it_shows_and_since_when(self):
        self.host()
        self.assertEqual(self.outline(disk=Stood(_utc(2026, 1, 15, 8, 10))), [
            "- nexus",
            "  - disk ⛔ — error since 2026-01-15 09:10:00 +01:00",
            "    - 97 % used",
            "  - memory ⚠️",
            "    - 88 % used",
        ])

    def test_a_bound_is_since_before(self):
        self.host()
        said = self.outline(memory=Stood(_utc(2026, 1, 13, 8, 0), before=True))
        self.assertIn("  - memory ⚠️ — warn since before 2026-01-13 09:00:00 +01:00",
                      said)

    def test_a_period_a_pin_began_says_so(self):
        self.host()
        said = self.outline(disk=Stood(_utc(2026, 1, 15, 8, 10),
                                       began="when its maintenance ended"))
        self.assertIn("  - disk ⛔ — error since 2026-01-15 09:10:00 +01:00, "
                      "when its maintenance ended", said)

    def test_a_pinned_node_holds_maintenance_since_its_pin(self):
        self.tree.upsert("/hemulen/backup", WARN, "took 5h 12m")
        self.tree.set_maintenance("/hemulen/backup", "the NAS is replaced",
                                  set_by="lex", expires_at=SOON)
        said = self.outline(backup=Stood(_utc(2026, 1, 15, 7, 0)))
        self.assertEqual(said[1], "  - backup 🛠️ (reported ⚠️) — maintenance since "
                                  "2026-01-15 08:00:00 +01:00")
        self.assertTrue(said[2].startswith("    - 🛠️ Maintenance — by lex, until "))

    def test_a_node_the_tree_keeps_no_period_of_says_nothing(self):
        self.host()
        said = self.outline()
        self.assertIn("  - disk ⛔", said)
        self.assertFalse([line for line in said if "since" in line], said)

    def test_a_line_carries_no_instant(self):
        self.tree.upsert("/ci/reviews", WARN,
                         [Entry("pr-1", "PR one waits", WARN)], members=True)
        said = self.outline(reviews=Stood(_utc(2026, 1, 15, 8, 10)))
        self.assertEqual(said, [
            "- ci",
            "  - reviews ⚠️ — warn since 2026-01-15 09:10:00 +01:00",
            "    - ⚠️ PR one waits",
        ])


class BranchInAnOutlineTests(_Tree):
    """Decision 3: a branch's line says what the branch itself holds."""

    def outline(self, **stood: Stood) -> list[str]:
        return lines(format_copy_markdown(self.root(), BERLIN,
                                          periods=periods(**stood)))

    def shelf(self, fan: StatusCode = WARN) -> None:
        self.tree.upsert("/storage/nas/disk", OK, "81 % used")
        self.tree.upsert("/storage/nas/fan", fan,
                         "the fan is loud" if fan is not OK else "quiet")
        self.tree.set_maintenance("/storage", "Shelf swap.", set_by="lex",
                                  expires_at=SOON)

    def test_a_pin_on_a_container_stands_on_its_line(self):
        # the pin was not in the outline, and what it silences read as alarming
        self.shelf()
        said = self.outline(storage=Stood(_utc(2026, 1, 15, 7, 0)))
        self.assertEqual(said[0], "- storage 🛠️ — maintenance since "
                                  "2026-01-15 08:00:00 +01:00")
        self.assertTrue(said[1].startswith("  - 🛠️ Maintenance — by lex, until "),
                        said[1])
        self.assertEqual(said[2:], [
            "    - Shelf swap.",
            "  - nas",
            "    - fan ⚠️",
            "      - the fan is loud",
        ])

    def test_a_pinned_container_is_listed_over_healthy_nodes_too(self):
        self.shelf(fan=OK)
        said = self.outline()
        self.assertEqual(said[0], "- storage 🛠️")
        self.assertTrue(said[1].startswith("  - 🛠️ Maintenance — by lex, until "))
        self.assertEqual(said[2:], ["    - Shelf swap."])

    def test_a_branch_with_a_status_of_its_own_is_listed_with_its_lines(self):
        # a gateway that itself answers 503 above healthy backends was not in the
        # document at all
        self.tree.upsert("/svc", ERROR, "the gateway itself answers 503")
        self.tree.upsert("/svc/a", OK, "fine")
        self.tree.upsert("/svc/b", OK, "fine")
        self.assertEqual(self.outline(svc=Stood(_utc(2026, 1, 15, 8, 10))), [
            "- svc ⛔ — error since 2026-01-15 09:10:00 +01:00",
            "  - the gateway itself answers 503",
        ])

    def test_its_own_lines_stand_above_what_is_beneath_it(self):
        self.tree.upsert("/aws", WARN,
                         [Entry("scope", "2 of 3 accounts are read", WARN)],
                         members=True)
        self.tree.upsert("/aws/prod", ERROR, "budget exceeded")
        self.assertEqual(self.outline(), [
            "- aws ⚠️",
            "  - ⚠️ 2 of 3 accounts are read",
            "  - prod ⛔",
            "    - budget exceeded",
        ])

    def test_a_branch_that_is_ok_or_declares_nothing_is_a_name(self):
        self.tree.upsert("/svc", OK, "the gateway answers")
        self.tree.upsert("/svc/a", ERROR, "down")
        self.host()
        said = self.outline()
        self.assertIn("- svc", said)
        self.assertIn("- nexus", said)

    def test_a_pinned_branch_keeps_what_it_reported(self):
        self.tree.upsert("/svc", ERROR, "the gateway itself answers 503")
        self.tree.upsert("/svc/a", OK, "fine")
        self.tree.set_maintenance("/svc", "known", set_by="lex", expires_at=SOON)
        said = self.outline()
        self.assertEqual(said[0], "- svc 🛠️ (reported ⛔)")
        self.assertEqual(said[-1], "  - the gateway itself answers 503")


class TreeDocumentTests(_Tree):
    """Decision 4: the tree's document has a head, and there is always one."""

    def document(self, **stood: Stood) -> list[str]:
        return lines(format_tree_markdown(self.root(), BERLIN, origin(),
                                          periods(**stood)))

    def test_it_opens_with_what_it_is_where_from_when_and_how_much(self):
        self.host()
        self.assertEqual(self.document(disk=Stood(_utc(2026, 1, 15, 8, 10))), [
            "## little-sister status ⛔",
            "",
            f"- **Dashboard:** {SITE}/status",
            f"- **As of:** {AS_OF}",
            "",
            "**Needs attention** — 2 of 3 nodes: 1 error ⛔, 1 warn ⚠️",
            "",
            "- nexus",
            "  - disk ⛔ — error since 2026-01-15 09:10:00 +01:00",
            "    - 97 % used",
            "  - memory ⚠️",
            "    - 88 % used",
        ])

    def test_the_head_and_the_outline_are_two_lists(self):
        # one list would space the outline's items like the head's
        self.host()
        rich = parse(str(render_markdown("\n".join(self.document()))))
        first, second = (part for part in rich.children
                         if getattr(part, "tag", "") == "ul")
        self.assertEqual(len([item for item in first.children
                              if getattr(item, "tag", "") == "li"]), 2)
        self.assertEqual(second.all(tag="li")[0].text().split()[0], "nexus")

    def test_a_tree_that_is_well_has_a_document_too(self):
        self.host(disk=OK)
        self.assertEqual(self.document(), [
            "## little-sister status ✅",
            "",
            f"- **Dashboard:** {SITE}/status",
            f"- **As of:** {AS_OF}",
            "",
            "**Nothing needs attention** — all 3 nodes are ok.",
        ])

    def test_a_pin_on_the_tree_itself_stands_in_the_head(self):
        # it is not set from the wall, and one that stands is stated like any other
        self.host()
        self.tree.set_maintenance("", "the site is being moved", set_by="lex",
                                  expires_at=SOON)
        said = self.document()
        self.assertEqual(said[0], "## little-sister status 🛠️")
        self.assertTrue(said[4].startswith("- 🛠️ Maintenance — by lex, until "),
                        said[4])
        self.assertEqual(said[5:9], [
            "  - the site is being moved",
            "",
            "**Under the pin** — 2 of 3 nodes would need attention: "
            "1 error ⛔, 1 warn ⚠️",
            "",
        ])
        self.assertEqual(said[9], "- nexus")

    def test_one_node_is_one_node(self):
        self.tree.upsert("/only", OK, "fine")
        self.assertEqual(self.document()[-1],
                         "**Nothing needs attention** — the one node is ok.")
        self.tree.upsert("/only", ERROR, "down")
        self.assertEqual(self.document()[5],
                         "**Needs attention** — 1 of 1 node: 1 error ⛔")

    def test_a_tree_nothing_reports_into_says_so(self):
        self.assertEqual(self.document()[-1], "**Nothing reports.**")
        self.assertEqual(self.document()[0], "## little-sister status ❓")

    def test_a_node_counts_where_it_shows_a_status_of_its_own(self):
        # nothing beneath it, or a branch that declares a status or is pinned
        self.host()                                             # three, two not ok
        self.tree.upsert("/svc", ERROR, "the gateway itself answers 503")
        self.tree.upsert("/svc/a", OK, "fine")                  # two, one not ok
        self.tree.upsert("/storage/nas/fan", OK, "quiet")
        self.tree.set_maintenance("/storage", "Shelf swap.", set_by="lex",
                                  expires_at=SOON)              # two, one pinned
        self.tree.upsert("/pending", UNDEFINED)                 # one, not ok
        # and a branch counts by its own status, not by what it rolls up to
        self.tree.upsert("/aws", WARN, "2 of 3 accounts are read")
        self.tree.upsert("/aws/prod", ERROR, "budget exceeded")     # two, both not ok
        self.assertEqual(
            self.document()[5],
            "**Needs attention** — 7 of 10 nodes: 3 error ⛔, 2 warn ⚠️, "
            "1 undefined ❓, 1 maintenance 🛠️")

    def test_the_count_is_the_number_of_findings_the_outline_lists(self):
        self.host()
        self.tree.upsert("/svc", ERROR, "the gateway itself answers 503")
        self.tree.upsert("/svc/a", OK, "fine")
        self.tree.upsert("/storage/nas/fan", WARN, "the fan is loud")
        self.tree.set_maintenance("/storage", "Shelf swap.", set_by="lex",
                                  expires_at=SOON)
        self.tree.upsert("/pending", UNDEFINED)
        self.tree.upsert("/aws", WARN, "2 of 3 accounts are read")
        self.tree.upsert("/aws/prod", ERROR, "budget exceeded")
        self.tree.upsert("/gw", OK, "the gateway answers", frequency_seconds=60)
        self.tree.upsert("/gw/backend", OK, "fine")
        root = self.tree.snapshot("", now=datetime.now(UTC) + timedelta(hours=2))
        said = lines(format_tree_markdown(root, BERLIN, origin()))
        count = re.match(r"\*\*Needs attention\*\* — (\d+) of (\d+) nodes: ", said[5])
        assert count is not None, said[5]
        # a node's line is its name and then the cue of what it shows; a line of
        # its own begins with its text, and a pin's with its mark
        findings = [line for line in said[7:]
                    if re.match(r" *- [a-z]+ (?:⛔|⚠️|❓|🛠️)", line)]
        self.assertEqual(int(count.group(1)), len(findings), said)
        self.assertEqual(len(findings), 9, findings)    # every one of them counted

    def test_a_tree_that_cannot_be_read_is_a_document_that_says_so(self):
        # the tree hands over no root where it has none to hand over
        self.assertEqual(lines(format_tree_markdown(None, BERLIN, origin())), [
            "## little-sister status ❓",
            "",
            f"- **Dashboard:** {SITE}/status",
            f"- **As of:** {AS_OF}",
            "",
            "**Nothing reports.**",
        ])


class BranchDocumentTests(_Tree):
    """Decision 5: a branch's document hands over what is beneath it."""

    def document(self, path: str, since: Stood | None = None, **stood: Stood) -> str:
        node = replace(self.node(path), timestamp=(
            _utc(2026, 1, 15, 8, 59) if self.node(path).timestamp else None))
        if since is None:
            return format_node_markdown(node, BERLIN, origin=origin(f"/{path}"),
                                        periods=periods(**stood))
        return format_node_markdown(node, BERLIN, since.at, before=since.before,
                                    began=since.began, origin=origin(f"/{path}"),
                                    periods=periods(**stood))

    def test_a_branch_that_declares_nothing_says_what_it_shows_and_why(self):
        self.host()
        shows = self.node("nexus").period
        assert shows is not None
        self.assertEqual(lines(self.document(
            "nexus", disk=Stood(_utc(2026, 1, 15, 8, 10)),
            memory=Stood(_utc(2026, 1, 13, 8, 0), before=True))), [
            "## nexus ⛔",
            "",
            "- **Path:** /nexus",
            f"- **Dashboard:** {SITE}/status/nexus",
            f"- **As of:** {AS_OF}",
            "- **Shown as:** error ⛔ — rolled up from the 3 nodes beneath it. "
            "It reports nothing of its own.",
            # the period of what it shows, above its observation (ADR-0132
            # decision 6)
            f"- **Status error** since {BERLIN.at(shows.began.at)}, begun by a "
            "reading of disk beneath it",
            "- **Observed:** 2026-01-15 09:59:00 +01:00",
            "- **Checked every:** 2m",
            "",
            "**Beneath it** — 2 of 3 nodes need attention",
            "",
            "- disk ⛔ — error since 2026-01-15 09:10:00 +01:00",
            "  - 97 % used",
            "- memory ⚠️ — warn since before 2026-01-13 09:00:00 +01:00",
            "  - 88 % used",
            "",
            "**Report**",
            "",
            "- **Uptime:** 83d",
            "",
            "**Configuration**",
            "",
            "- **host:** nexus",
        ])

    def test_a_healthy_branch_says_that_nothing_needs_attention(self):
        self.host(disk=OK)
        said = lines(self.document("nexus"))
        self.assertEqual(said[0], "## nexus ✅")
        self.assertIn("- **Shown as:** ok ✅ — rolled up from the 3 nodes beneath "
                      "it. It reports nothing of its own.", said)
        self.assertIn("**Beneath it** — nothing needs attention.", said)
        self.assertFalse([line for line in said if line.startswith("- cpu")])

    def test_what_it_shows_is_what_rolls_up_and_a_pinned_node_is_still_listed(self):
        # a pinned node counts for nothing in what its branch shows (ADR-0039), so
        # the sentence makes no claim that every node beneath it shows the same
        self.host()
        self.tree.upsert("/nexus/memory", OK, "38 % used")
        self.tree.set_maintenance("/nexus/disk", "a new disk is on its way",
                                  set_by="lex", expires_at=SOON)
        said = lines(self.document("nexus"))
        self.assertEqual(said[0], "## nexus ✅")
        self.assertIn("- **Shown as:** ok ✅ — rolled up from the 3 nodes beneath "
                      "it. It reports nothing of its own.", said)
        self.assertIn("**Beneath it** — 1 of 3 nodes needs attention", said)
        self.assertIn("- disk 🛠️ (reported ⛔)", said)

    def test_one_node_beneath_it_is_one_node(self):
        self.tree.upsert("/hemulen/findmy", ERROR, "stale")
        said = lines(self.document("hemulen"))
        self.assertIn("- **Shown as:** error ⛔ — rolled up from the one node "
                      "beneath it. It reports nothing of its own.", said)
        self.assertIn("**Beneath it** — 1 of 1 node needs attention", said)

    def test_a_branch_nothing_beneath_has_reported_into_says_so(self):
        self.tree.upsert("/pending/a", UNDEFINED)
        self.tree.upsert("/pending/b", UNDEFINED)
        said = lines(self.document("pending"))
        self.assertEqual(said[0], "## pending ❓")
        self.assertIn("- **Shown as:** undefined ❓ — rolled up from the 2 nodes "
                      "beneath it. It reports nothing of its own.", said)

    def test_a_pinned_container_states_its_pin_and_what_it_silences(self):
        self.tree.upsert("/storage/nas/disk", OK, "81 % used")
        self.tree.upsert("/storage/nas/fan", WARN, "the fan is loud")
        self.tree.set_maintenance("/storage", "Shelf swap.", set_by="lex",
                                  expires_at=SOON)
        said = lines(self.document("storage", Stood(_utc(2026, 1, 15, 7, 0)),
                                   fan=Stood(_utc(2026, 1, 14, 7, 0))))
        self.assertEqual(said[0], "## storage 🛠️")
        self.assertEqual(said[5], "- **Shown as:** maintenance 🛠️ — a maintenance pin "
                                  "is in force on it and on the 2 nodes beneath it. "
                                  "It reports nothing of its own.")
        self.assertTrue(said[6].startswith("- 🛠️ Maintenance — by lex, until "))
        self.assertEqual(said[7:], [
            "  - Shelf swap.",
            "- **Status maintenance** since 2026-01-15 08:00:00 +01:00",
            "",
            "**Beneath it**, under the pin — 1 of 2 nodes would need attention",
            "",
            "- nas",
            "  - fan ⚠️ — warn since 2026-01-14 08:00:00 +01:00",
            "    - the fan is loud",
        ])
        self.assertNotIn("Reported", "\n".join(said))
        self.assertNotIn("Not yet observed", "\n".join(said))

    def test_a_branch_that_declares_a_status_keeps_its_reading_and_its_lines(self):
        self.tree.upsert("/aws", WARN,
                         [Entry("scope", "2 of 3 accounts are read", WARN)],
                         members=True)
        self.tree.upsert("/aws/prod", ERROR, "budget exceeded")
        shows = self.node("aws").period
        assert shows is not None
        said = lines(self.document("aws", Stood(_utc(2026, 1, 15, 7, 0))))
        self.assertEqual(said[0], "## aws ⛔")
        self.assertEqual(said[5:14], [
            "- **Reported:** warn ⚠️",
            "- **Shown as:** error ⛔ — rolled up from its own reading and the one "
            "node beneath it.",
            # the period of what it shows, above that of its own status (ADR-0132
            # decision 6)
            f"- **Status error** since {BERLIN.at(shows.began.at)}, begun by a "
            "reading of prod beneath it",
            "- **Its own status warn** since 2026-01-15 08:00:00 +01:00",
            "- **Last observed:** 2026-01-15 09:59:00 +01:00",
            "",
            "**Reasons**",
            "",
            "- ⚠️ 2 of 3 accounts are read",
        ])
        self.assertEqual(said[14:], [
            "",
            "**Beneath it** — 1 of 1 node needs attention",
            "",
            "- prod ⛔",
            "  - budget exceeded",
        ])

    def test_a_branch_that_shows_what_it_reported_says_it_once(self):
        self.tree.upsert("/svc", ERROR, "the gateway itself answers 503")
        self.tree.upsert("/svc/a", OK, "fine")
        said = self.document("svc")
        self.assertIn("- **Reported:** error ⛔", lines(said))
        self.assertNotIn("Shown as", said)
        self.assertIn("**Beneath it** — nothing needs attention.", lines(said))

    def test_a_pinned_branch_that_reported_says_what_its_check_measured(self):
        self.tree.upsert("/svc", ERROR, "the gateway itself answers 503")
        self.tree.upsert("/svc/a", OK, "fine")
        self.tree.set_maintenance("/svc", "known", set_by="lex", expires_at=SOON)
        said = lines(self.document("svc"))
        self.assertIn("- **Reported:** error ⛔", said)
        self.assertIn("- **Shown as:** maintenance 🛠️ — a maintenance pin is in force "
                      "on it and on the one node beneath it. The reported reading "
                      "above is what its check measured.", said)

    def test_a_leafs_document_is_as_it_was(self):
        self.tree.upsert("/services/api", ERROR, "down", frequency_seconds=900)
        node = replace(self.node("services/api"),
                       timestamp=_utc(2026, 1, 15, 8, 59))
        self.assertEqual(lines(format_node_markdown(node, BERLIN)), [
            "## api ⛔",
            "",
            "- **Path:** /services/api",
            "- **Reported:** error ⛔",
            "- **Observed:** 2026-01-15 09:59:00 +01:00",
            "- **Checked every:** 15m",
            "",
            "**Reasons**",
            "",
            "- down",
        ])


class StaleReadingTests(_Tree):
    """A stale reading is said by the node whose reading it is, and a branch whose
    own reading is stale is counted and listed as the tree counts it."""

    def later(self, path: str = "") -> StatusSnapshot:
        found = self.tree.snapshot(path, now=datetime.now(UTC) + timedelta(hours=2))
        assert found is not None, path
        return found

    def test_a_branch_whose_own_reading_is_stale_is_counted_and_listed(self):
        # a gateway whose check stopped, above backends that are well: the tree
        # shows a warning, and its document may not say that nothing needs attention
        self.tree.upsert("/svc", OK, "the gateway answers", frequency_seconds=60)
        self.tree.upsert("/svc/a", OK, "fine")
        root = self.later()
        self.assertEqual((root.code, root.children[0].code), (WARN, WARN))
        self.assertEqual(lines(format_tree_markdown(root, BERLIN, origin())), [
            "## little-sister status ⚠️",
            "",
            f"- **Dashboard:** {SITE}/status",
            f"- **As of:** {AS_OF}",
            "",
            "**Needs attention** — 1 of 2 nodes: 1 warn ⚠️",
            "",
            "- svc ⚠️ (stale)",
            "  - the gateway answers",
        ])

    def test_a_failure_gone_stale_is_not_softened(self):
        self.tree.upsert("/svc", ERROR, "the gateway itself answers 503",
                         frequency_seconds=60)
        self.tree.upsert("/svc/a", OK, "fine")
        self.assertEqual(lines(format_copy_markdown(self.later(), BERLIN)), [
            "- svc ⛔ (stale)",
            "  - the gateway itself answers 503",
        ])

    def test_a_branch_above_a_stale_node_leaves_the_word_to_that_node(self):
        self.tree.upsert("/svc", ERROR, "the gateway itself answers 503")
        self.tree.upsert("/svc/a", OK, "fine", frequency_seconds=60)
        root = self.later()
        self.assertTrue(root.children[0].stale)      # the alarm is the branch's too
        self.assertEqual(lines(format_copy_markdown(root, BERLIN)), [
            "- svc ⛔",
            "  - the gateway itself answers 503",
            "  - a ⚠️ (stale)",
            "    - fine",
        ])

    def test_a_branchs_document_says_stale_of_its_own_reading_only(self):
        self.tree.upsert("/svc", OK, "the gateway answers")
        self.tree.upsert("/svc/a", OK, "fine", frequency_seconds=60)
        said = lines(format_node_markdown(self.later("svc"), BERLIN))
        self.assertFalse([line for line in said if "**Stale**" in line], said)
        self.assertIn("- a ⚠️ (stale)", said)

        self.tree.upsert("/gw", OK, "the gateway answers", frequency_seconds=60)
        self.tree.upsert("/gw/a", OK, "fine")
        said = lines(format_node_markdown(self.later("gw"), BERLIN))
        self.assertIn("- **Stale** — last observed 2h ago", said)
        self.assertIn("- **Shown as:** warn ⚠️ — rolled up from its own reading and "
                      "the one node beneath it.", said)
        self.assertIn("**Beneath it** — nothing needs attention.", said)


class PeriodWithoutAnObservationTests(_Tree):
    """Decision 6: a period is stated wherever there is one."""

    def test_a_pinned_node_nothing_has_written_states_its_period(self):
        self.tree.set_about("/svc", "declared, never reported")
        self.tree.set_maintenance("/svc", "not built yet", set_by="lex",
                                  expires_at=SOON)
        node = self.node("svc")
        self.assertIsNone(node.timestamp)
        said = lines(format_node_markdown(node, BERLIN, _utc(2026, 1, 15, 7, 0)))
        self.assertIn("- **Status maintenance** since 2026-01-15 08:00:00 +01:00", said)
        self.assertNotIn("- **Not yet observed.**", said)
        # and claims no measurement: there is none for the pin to stand over
        self.assertIn("- **Shown as:** maintenance 🛠️ — a maintenance pin is in "
                      "force; no check has written this node.", said)
        self.assertFalse([line for line in said if "observed" in line.lower()], said)

    def test_a_node_with_neither_still_says_not_yet_observed(self):
        self.tree.set_about("/svc", "declared, never reported")
        self.assertIn("- **Not yet observed.**",
                      lines(format_node_markdown(self.node("svc"), BERLIN)))


class RouteTests(TestCase):
    """What the routes supply: the address the request came by, the instant, and
    the periods the tree keeps."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", self._original)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        clock = mock.patch.object(app_module, "_now", return_value=datetime(
            2026, 1, 15, 9, 0, tzinfo=UTC))
        clock.start()
        self.addCleanup(clock.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/nexus", UNDEFINED, None, frequency_seconds=120)
        self.tree.upsert("/nexus/cpu", OK, "9 % busy")
        self.tree.upsert("/nexus/disk", OK, "61 % used")
        self.tree.upsert("/nexus/disk", ERROR, "97 % used")
        self.tree.upsert("/ci/reviews", WARN,
                         [Entry("pr-1", "PR one waits", WARN)], members=True)

    def page(self, url: str, status: int = 200):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return parse(response.get_data(as_text=True))

    def source(self, url: str) -> list[str]:
        return lines(self.page(url).with_id("ls-copy-source").source())

    def as_of(self) -> str:
        return f"- **As of:** {app_module._copy_style().at(MADE)}"

    def test_the_trees_document_names_the_wall_and_dates_its_findings(self):
        said = self.source("/copy")
        self.assertEqual(said[:6], [
            "## little-sister status ⛔",
            "",
            "- **Dashboard:** http://localhost/status",
            self.as_of(),
            "",
            "**Needs attention** — 2 of 3 nodes: 1 error ⛔, 1 warn ⚠️",
        ])
        disk, = (line for line in said if line.lstrip().startswith("- disk"))
        self.assertRegex(disk, r"^  - disk ⛔ — error since \d{4}-\d\d-\d\d ")
        self.assertNotIn("since before", disk)       # the tree saw it turn
        reviews, = (line for line in said if line.lstrip().startswith("- reviews"))
        self.assertRegex(reviews, r"^  - reviews ⚠️ — warn since before \d{4}-")

    def test_a_document_names_its_nodes_handbook_and_leads_into_it(self):
        # ADR-0133 decisions 3 and 4: from the base the request came by
        self.tree.set_handbook("/nexus/disk", "## When it fills\n")
        self.tree.upsert("/nexus/disk", ERROR, "97 % used — [what to do]"
                                               "(handbook#when-it-fills)")
        said = self.source("/copy/nexus/disk")
        self.assertEqual(said[3:6], [
            "- **Dashboard:** http://localhost/status/nexus/disk",
            "- **Handbook:** http://localhost/handbook/nexus/disk", self.as_of()])
        self.assertIn("[what to do](http://localhost/handbook/nexus/disk#when-it-"
                      "fills)", "\n".join(said))
        # the tree's, the root's handbook at its own address
        self.tree.set_handbook("", "## Whom to call\n")
        self.assertEqual(self.source("/copy")[3],
                         "- **Handbook:** http://localhost/handbook")

    def test_a_tree_that_is_well_is_offered_as_a_document(self):
        self.tree.upsert("/nexus/disk", OK, "61 % used")
        self.tree.upsert("/ci/reviews", OK, [Entry("pr-1", "merged", OK)],
                         members=True)
        page = self.page("/copy")
        self.assertEqual(lines(page.with_id("ls-copy-source").source())[-1],
                         "**Nothing needs attention** — all 3 nodes are ok.")
        self.assertEqual(len(page.with_id("ls-copy-page").all(tag="button")), 2)

    def test_a_branchs_document_names_its_page_and_what_is_beneath_it(self):
        said = self.source("/copy/nexus")
        self.assertEqual(said[2:5], ["- **Path:** /nexus",
                                     "- **Dashboard:** http://localhost/status/nexus",
                                     self.as_of()])
        self.assertIn("**Beneath it** — 1 of 2 nodes needs attention", said)
        self.assertRegex(said[said.index("**Beneath it** — 1 of 2 nodes needs "
                                         "attention") + 2],
                         r"^- disk ⛔ — error since \d{4}-")

    def test_a_branch_with_a_period_of_its_own_dates_what_is_beneath_it_too(self):
        self.tree.set_maintenance("/ci", "frozen for the release", set_by="lex",
                                  expires_at=SOON)
        said = self.source("/copy/ci")
        self.assertRegex("\n".join(said), r"- \*\*Status maintenance\*\* since \d{4}-")
        reviews, = (line for line in said if line.startswith("- reviews"))
        self.assertRegex(reviews, r"^- reviews ⚠️ — warn since before \d{4}-")

    def test_a_leafs_document_names_its_page(self):
        said = self.source("/copy/nexus/disk")
        self.assertEqual(said[3], "- **Dashboard:** http://localhost/status/nexus/disk")
        self.assertEqual(said[4], self.as_of())

    def test_a_lines_document_names_the_line_on_its_nodes_page(self):
        said = self.source("/copy/ci/reviews?reason=pr-1")
        self.assertEqual(
            said[3], "- **Dashboard:** http://localhost/status/ci/reviews?reason=pr-1")
        self.assertEqual(said[4], self.as_of())

    def test_a_pinned_node_nothing_has_written_states_its_period(self):
        # decision 6: its Time card and its document said *Not yet observed* and
        # nothing else, of a declared node; a container's document said the same,
        # and its page drew no Time card at all
        self.tree.set_about("/declared", "named in the configuration, never read")
        self.tree.set_maintenance("/declared", "not built yet", set_by="lex",
                                  expires_at=SOON)
        self.tree.set_maintenance("/ci", "frozen for the release", set_by="lex",
                                  expires_at=SOON)
        for url in ("/status/declared", "/status/ci"):
            with self.subTest(url=url):
                body = self.client.get(url).get_data(as_text=True)
                self.assertRegex(body,
                                 r"Status <strong>maintenance</strong>\s+since ")
                self.assertNotIn("Not yet observed.", body)
                self.assertNotIn("Last observed", body)
        for url in ("/copy/declared", "/copy/ci"):
            with self.subTest(url=url):
                said = "\n".join(self.source(url))
                self.assertRegex(said, r"- \*\*Status maintenance\*\* since \d{4}-")
                self.assertNotIn("Not yet observed", said)
