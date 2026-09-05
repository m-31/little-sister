"""Reachability probing for the links page (ADR-0030 §9-10).

No test here touches the network: every case patches ``_request``, which is the one
place this module reaches a socket (through :func:`little_sister.fetch.fetch`, which
has its own suite). A suite that reached the internet would be slow, flaky and
different on a laptop with a proxy — and the classification these tests are about
happens entirely on this side of the wire.

``_request`` returns **any** status and raises only when the request never got one,
which is `fetch`'s contract: a `404` is an answer, and the stand-ins below say so by
returning it rather than by raising.
"""

import http.client
import socket
import ssl
import threading
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock

from little_sister import link_probe
from little_sister.icons import Icon, IconFile
from little_sister.links import Group, Link, LinksConfig, ProbeSettings
from little_sister.transport import Fault, RemoteError


def config_with(*links_, **probe):
    """A configuration holding one group of entries, with probe settings applied."""
    return LinksConfig(groups=(Group(title="T", links=tuple(links_)),),
                       probe=ProbeSettings(**probe))


def remote(url):
    """An icon that lives at somebody else's origin — the only kind worth probing."""
    return Icon(name="mark", on_light=IconFile(url=url), on_dark=IconFile(url=url))


def answering(*statuses):
    """A ``_request`` stand-in returning the given statuses in turn, recording the
    methods it was asked for."""
    calls = []

    def request(url, method):
        calls.append((url, method))
        answer = statuses[min(len(calls) - 1, len(statuses) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer

    request.calls = calls
    return request


def transport_failure(reason):
    """What `fetch` raises when the request never reached a status, carrying the
    original exception as ``__cause__`` — which is the channel `_transport_verdict`
    reads to word the failure in the page's vocabulary rather than urllib's."""
    error = RemoteError("request failed for HEAD https://x.example.org/",
                        fault=Fault.TRANSIENT)
    error.__cause__ = reason
    return error


class TargetTests(TestCase):
    """What a configuration actually asks to be probed."""

    def test_a_link_is_probed_only_when_it_opts_in(self):
        config = config_with(Link(title="A", url="https://a.example.org/"),
                             Link(title="B", url="https://b.example.org/",
                                  check=True),
                             links=True)
        self.assertEqual(link_probe.targets(config), ("https://b.example.org/",))

    def test_the_block_can_switch_every_link_off(self):
        # The default: most entries are auth-walled, where a 403 says three
        # different things (ADR-0030 §10).
        config = config_with(Link(title="B", url="https://b.example.org/",
                                  check=True))
        self.assertEqual(link_probe.targets(config), ())

    def test_one_url_named_twice_is_one_target(self):
        config = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True),
                             Link(title="Also A", url="https://a.example.org/",
                                  check=True),
                             links=True)
        self.assertEqual(link_probe.targets(config), ("https://a.example.org/",))

    def test_only_a_remote_icon_is_a_target(self):
        # A local file and a pack member are settled offline at load, so there is
        # nothing left for a probe to discover about them.
        local = Icon(name="mark", on_light=IconFile(path=Path("/tmp/mark.svg")),
                     on_dark=IconFile(path=Path("/tmp/mark.svg")))
        config = LinksConfig(
            icons={"local": local, "far": remote("https://i.example.org/m.svg")},
            groups=(Group(title="T", links=(
                Link(title="A", url="https://a.example.org/", icon="local"),
                Link(title="B", url="https://b.example.org/", icon="far"))),))
        self.assertEqual(link_probe.targets(config),
                         ("https://i.example.org/m.svg",))

    def test_a_pair_that_is_one_file_is_one_target(self):
        config = LinksConfig(
            icons={"far": remote("https://i.example.org/m.svg")},
            groups=(Group(title="T", links=(
                Link(title="A", url="https://a.example.org/", icon="far"),)),))
        self.assertEqual(len(link_probe.targets(config)), 1)

    def test_an_icon_no_entry_uses_is_not_probed(self):
        config = LinksConfig(
            icons={"far": remote("https://i.example.org/m.svg")},
            groups=(Group(title="T", links=(
                Link(title="A", url="https://a.example.org/"),)),))
        self.assertEqual(link_probe.targets(config), ())

    def test_a_suppressed_icon_is_not_probed(self):
        config = LinksConfig(
            icons={"off": Icon(name="off", suppressed=True)},
            groups=(Group(title="T", links=(
                Link(title="A", url="https://a.example.org/", icon="off"),)),))
        self.assertEqual(link_probe.targets(config), ())

    def test_icons_can_be_switched_off(self):
        config = LinksConfig(
            icons={"far": remote("https://i.example.org/m.svg")},
            probe=ProbeSettings(icons=False),
            groups=(Group(title="T", links=(
                Link(title="A", url="https://a.example.org/", icon="far"),)),))
        self.assertEqual(link_probe.targets(config), ())

    def test_the_entrys_own_favicon_is_never_probed(self):
        # It is the fallback for an entry that named no mark; probing it would turn
        # every open into one request per distinct host on the page.
        config = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True), links=True)
        self.assertEqual(link_probe.targets(config), ("https://a.example.org/",))


class VerdictTests(TestCase):
    """Which answers mean *gone*, which mean *guarded*, and which mean *no idea*."""

    def probe(self, request, alive=frozenset({200, 301, 302, 401, 403})):
        with mock.patch.object(link_probe, "_request", request):
            return link_probe._probe("https://x.example.org/", alive)

    def test_an_agreed_status_is_alive(self):
        self.assertIs(self.probe(answering(200)).alive, True)

    def test_an_auth_wall_is_alive_not_dead(self):
        # 403 may mean "not signed in", "your agent is blocked" or a real wall, and
        # the three are indistinguishable from here (ADR-0030 §10).
        for code in (401, 403):
            self.assertIs(self.probe(answering(code)).alive, True)

    def test_a_redirect_is_reported_rather_than_followed(self):
        # 301 and 302 are in the default alive list, which they could never reach if
        # urllib quietly followed them to whatever answers at the end.
        verdict = self.probe(answering(301))
        self.assertIs(verdict.alive, True)
        self.assertEqual(verdict.detail, "HTTP 301")

    def test_gone_is_dead(self):
        for code in (404, 410):
            verdict = self.probe(answering(code))
            self.assertIs(verdict.alive, False)
            self.assertEqual(verdict.detail, f"HTTP {code}")

    def test_anything_else_is_no_answer_rather_than_a_death(self):
        verdict = self.probe(answering(500))
        self.assertIsNone(verdict.alive)
        self.assertEqual(verdict.detail, "HTTP 500")

    def test_head_falls_back_to_get(self):
        # A 405 is a server's opinion about methods, not about existence.
        request = answering(405, 200)
        verdict = self.probe(request)
        self.assertIs(verdict.alive, True)
        self.assertEqual([method for _, method in request.calls], ["HEAD", "GET"])

    def test_a_server_that_does_not_implement_head_is_asked_again_too(self):
        request = answering(501, 200)
        self.assertIs(self.probe(request).alive, True)
        self.assertEqual([method for _, method in request.calls], ["HEAD", "GET"])

    def test_a_name_that_does_not_resolve_is_dead(self):
        error = transport_failure(
            urllib.error.URLError(socket.gaierror("nodename nor servname")))
        verdict = self.probe(answering(error))
        self.assertIs(verdict.alive, False)
        self.assertEqual(verdict.detail, "host not found")

    def test_a_refused_port_is_dead(self):
        error = transport_failure(
            urllib.error.URLError(ConnectionRefusedError()))
        verdict = self.probe(answering(error))
        self.assertIs(verdict.alive, False)
        self.assertEqual(verdict.detail, "connection refused")

    def test_a_timeout_is_no_answer_rather_than_a_death(self):
        # An internal host behind a slow VPN answers eventually; calling that dead
        # is how a page starts crying wolf.
        error = transport_failure(urllib.error.URLError(TimeoutError()))
        verdict = self.probe(answering(error))
        self.assertIsNone(verdict.alive)
        self.assertEqual(verdict.detail, "no answer in time")

    def test_a_tls_failure_says_so_and_is_not_a_death(self):
        """The second branch nothing exercised (roadmap item 6). A bad certificate or a
        protocol mismatch is emphatically **not** a retired host — the port answered and
        the server is there — so it reads as unknown with a detail an operator can act
        on, rather than as gone. It is also the one verdict here that names a fix.
        """
        error = transport_failure(
            urllib.error.URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED")))
        verdict = self.probe(answering(error))
        self.assertIsNone(verdict.alive)
        self.assertEqual(verdict.detail, "TLS handshake failed")

    def test_the_transport_exception_never_reaches_the_page(self):
        error = transport_failure(
            urllib.error.URLError(OSError("proxy /etc/ssl/certs said no")))
        self.assertEqual(self.probe(answering(error)).detail, "no answer")

    def test_a_failed_answer_is_what_the_page_draws(self):
        self.assertFalse(self.probe(answering(200)).failed)
        self.assertTrue(self.probe(answering(404)).failed)
        self.assertTrue(self.probe(answering(500)).failed)


class PassTests(TestCase):
    """The trigger: who starts a pass, when, and how many run at once."""

    def setUp(self):
        self.config = config_with(
            Link(title="A", url="https://a.example.org/", check=True),
            Link(title="B", url="https://b.example.org/", check=True),
            links=True)

    def run_pass(self, request, config=None):
        with mock.patch.object(link_probe, "_request", request):
            event = link_probe.refresh_if_due(config or self.config)
            if event is not None:
                self.assertTrue(event.wait(5), "the pass did not finish")
        return event

    def test_an_open_probes_what_has_never_been_asked_about(self):
        request = answering(200)
        self.assertIsNotNone(self.run_pass(request))
        self.assertEqual(len(request.calls), 2)
        self.assertEqual(set(link_probe.results()),
                         {"https://a.example.org/", "https://b.example.org/"})

    def test_a_second_open_inside_the_interval_asks_nothing_again(self):
        self.run_pass(answering(200))
        second = answering(200)
        self.assertIsNone(self.run_pass(second))
        self.assertEqual(second.calls, [])

    def age_every_answer(self, by):
        """Push every held answer back in time, the way an idle process does."""
        for url, verdict in list(link_probe.results().items()):
            link_probe._results[url] = link_probe.Verdict(
                url=url, alive=verdict.alive, detail=verdict.detail,
                checked_at=datetime.now() - by)

    def test_an_answer_older_than_the_interval_is_refreshed(self):
        self.run_pass(answering(200))
        self.age_every_answer(timedelta(hours=7))
        second = answering(200)
        self.assertIsNotNone(self.run_pass(second))
        self.assertEqual(len(second.calls), 2)

    def test_a_shorter_interval_is_honored(self):
        config = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True), links=True, interval="1h")
        self.run_pass(answering(200), config)
        self.age_every_answer(timedelta(hours=2))
        second = answering(200)
        self.assertIsNotNone(self.run_pass(second, config))
        self.assertEqual(len(second.calls), 1)

    def test_an_entry_added_since_the_last_pass_is_asked_on_the_next_open(self):
        # A target nothing has ever asked about counts as infinitely old: the
        # operator who just added a link should not wait six hours to see it.
        self.run_pass(answering(200))
        grown = config_with(
            Link(title="A", url="https://a.example.org/", check=True),
            Link(title="B", url="https://b.example.org/", check=True),
            Link(title="C", url="https://c.example.org/", check=True),
            links=True)
        third = answering(200)
        self.assertIsNotNone(self.run_pass(third, grown))
        self.assertEqual(len(third.calls), 3)

    def test_a_url_the_file_no_longer_names_is_forgotten(self):
        self.run_pass(answering(200))
        shrunk = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True), links=True)
        with mock.patch.object(link_probe, "_request", answering(200)):
            link_probe.start_pass(shrunk).wait(5)
        self.assertEqual(set(link_probe.results()), {"https://a.example.org/"})

    def test_nothing_to_probe_starts_nothing(self):
        request = answering(200)
        with mock.patch.object(link_probe, "_request", request):
            self.assertIsNone(link_probe.refresh_if_due(LinksConfig()))
        self.assertEqual(request.calls, [])

    def test_readers_arriving_together_cost_one_pass(self):
        # Ten readers must not become ten sweeps: the second caller is handed the
        # running pass, not a new one.
        held = threading.Event()
        started = threading.Event()

        def request(url, method):
            started.set()
            held.wait(5)
            return 200

        with mock.patch.object(link_probe, "_request", request):
            first = link_probe.start_pass(self.config)
            self.assertTrue(started.wait(5))
            second = link_probe.start_pass(self.config)
            self.assertIs(second, first)
            held.set()
            self.assertTrue(first.wait(5))

    def test_a_pass_that_throws_leaves_no_pass_running(self):
        # A links page must never be the reason an instance looks broken — and a
        # stuck flag would mean no pass ever ran again.
        with mock.patch.object(link_probe, "targets",
                               side_effect=RuntimeError("boom")):
            self.assertTrue(link_probe.start_pass(self.config).wait(5))
        self.assertIsNone(link_probe._running)


class CheckNowTests(TestCase):
    """The deliberate press: it waits, it joins, and it has a floor."""

    def setUp(self):
        self.config = config_with(
            Link(title="A", url="https://a.example.org/", check=True),
            Link(title="B", url="https://b.example.org/", check=True),
            links=True)

    def test_it_waits_for_its_own_answers(self):
        # *Never block* is a rule about the open, not about the reader: somebody
        # pressing this asked for the network, so the answers are there on return.
        request = answering(200)
        with mock.patch.object(link_probe, "_request", request):
            self.assertTrue(link_probe.refresh_now(self.config))
        self.assertEqual(len(request.calls), 2)
        self.assertEqual(len(link_probe.results()), 2)

    def test_it_probes_even_when_the_answers_are_fresh(self):
        # The whole point: the time gate is exactly wrong for the person who has
        # just fixed a URL, so this ignores it — the gap below is the only floor.
        with mock.patch.object(link_probe, "_request", answering(200)):
            link_probe.refresh_now(self.config)
        link_probe._last_forced = None          # only the interval is in the way
        second = answering(200)
        with mock.patch.object(link_probe, "_request", second):
            link_probe.refresh_now(self.config)
        self.assertEqual(len(second.calls), 2)

    def test_a_press_inside_the_gap_spends_nothing(self):
        # The abuse story in full: one control on the instance lets a reader spend
        # outbound requests on purpose, so it has a floor.
        with mock.patch.object(link_probe, "_request", answering(200)):
            link_probe.refresh_now(self.config)
        second = answering(200)
        with mock.patch.object(link_probe, "_request", second):
            self.assertTrue(link_probe.refresh_now(self.config))
        self.assertEqual(second.calls, [])

    def test_a_press_past_the_gap_probes_again(self):
        with mock.patch.object(link_probe, "_request", answering(200)):
            link_probe.refresh_now(self.config)
        link_probe._last_forced = datetime.now() - timedelta(
            seconds=link_probe.MIN_FORCED_GAP + 1)
        second = answering(200)
        with mock.patch.object(link_probe, "_request", second):
            link_probe.refresh_now(self.config)
        self.assertEqual(len(second.calls), 2)

    def test_a_press_mid_pass_joins_it_rather_than_queueing_a_second(self):
        # Two presses two seconds apart return together, and cost one sweep.
        held = threading.Event()
        started = threading.Event()

        def request(url, method):
            started.set()
            held.wait(5)
            return 200

        with mock.patch.object(link_probe, "_request", request):
            opened = link_probe.start_pass(self.config)
            self.assertTrue(started.wait(5))
            joined = threading.Event()

            def press():
                link_probe.refresh_now(self.config, deadline=5)
                joined.set()

            threading.Thread(target=press, daemon=True).start()
            self.assertFalse(joined.wait(0.2))   # it is waiting, not returning
            held.set()
            self.assertTrue(opened.wait(5))
            self.assertTrue(joined.wait(5))
        # one pass, so two answers and not four
        self.assertEqual(len(link_probe.results()), 2)

    def test_the_deadline_returns_the_reader_to_a_page_that_says_so(self):
        # A hung internal host costs one stale row, never a stuck request thread:
        # the pass carries on behind the response, which is what `running` says.
        held = threading.Event()

        def request(url, method):
            held.wait(5)
            return 200

        with mock.patch.object(link_probe, "_request", request):
            try:
                self.assertFalse(link_probe.refresh_now(self.config,
                                                        deadline=0.1))
                self.assertTrue(link_probe.is_running())
                self.assertEqual(link_probe.results(), {})
            finally:
                held.set()
            # Let it finish while the stand-in is still installed, so no probe
            # thread outlives the patch and reaches for the real network.
            self.assertTrue(link_probe.start_pass(self.config).wait(5))

    def test_nothing_to_probe_is_answered_at_once(self):
        request = answering(200)
        with mock.patch.object(link_probe, "_request", request):
            self.assertTrue(link_probe.refresh_now(LinksConfig()))
        self.assertEqual(request.calls, [])


class PageViewTests(TestCase):
    """What the render is handed."""

    def view(self, config, request=None):
        with mock.patch.object(link_probe, "_request", request or answering(200)):
            event = link_probe.refresh_if_due(config)
            if event is not None:
                event.wait(5)
        return link_probe.page_view(config)

    def test_a_page_that_probes_nothing_shows_no_freshness_line(self):
        view = link_probe.page_view(LinksConfig())
        self.assertFalse(view.active)
        self.assertIsNone(view.checked_at)

    def test_the_age_is_the_newest_answer_the_page_holds(self):
        config = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True), links=True)
        view = self.view(config)
        self.assertTrue(view.active)
        self.assertIsNotNone(view.checked_at)
        self.assertLess((datetime.now() - view.checked_at).total_seconds(), 5)

    def test_a_dead_entry_carries_its_verdict(self):
        config = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True), links=True)
        view = self.view(config, answering(404))
        verdict = view.verdicts["https://a.example.org/"]
        self.assertIs(verdict.alive, False)
        self.assertTrue(verdict.failed)

    def test_a_dead_icon_is_named_by_the_mark_it_draws(self):
        # An icon is not a row on this page, so its verdict joins the configuration
        # problems, which have the same audience.
        config = LinksConfig(
            icons={"far": remote("https://i.example.org/m.svg")},
            groups=(Group(title="T", links=(
                Link(title="A", url="https://a.example.org/", icon="far"),
                Link(title="B", url="https://b.example.org/", icon="far"))),))
        view = self.view(config, answering(404))
        self.assertEqual([failure.name for failure in view.icon_failures], ["far"])
        self.assertEqual(view.icon_failures[0].verdict.detail, "HTTP 404")

    def test_a_live_icon_is_not_a_problem(self):
        config = LinksConfig(
            icons={"far": remote("https://i.example.org/m.svg")},
            groups=(Group(title="T", links=(
                Link(title="A", url="https://a.example.org/", icon="far"),)),))
        self.assertEqual(self.view(config).icon_failures, ())

    def test_a_pass_in_flight_is_reported(self):
        # The page does not poll, so a reader whose *check now* hit the deadline
        # learns from this that the rest is one reload away.
        config = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True), links=True)
        held = threading.Event()

        def request(url, method):
            held.wait(5)
            return 200

        with mock.patch.object(link_probe, "_request", request):
            done = link_probe.start_pass(config)
            try:
                self.assertTrue(link_probe.page_view(config).running)
            finally:
                held.set()
            self.assertTrue(done.wait(5))
        self.assertFalse(link_probe.page_view(config).running)


class RequestPolicyTests(TestCase):
    """What `_request` asks `fetch` for. Three of these are decisions rather than
    defaults, and the page's whole reading of a `301` rests on the first."""

    def _asked(self):
        with mock.patch.object(link_probe, "fetch",
                               return_value=mock.Mock(status=200)) as called:
            self.assertEqual(
                link_probe._request("https://x.example.org/", "HEAD"), 200)
        return called.call_args

    def test_a_redirect_is_reported_rather_than_followed(self):
        # `301` and `302` are in the default `alive:` list, which they could never
        # reach if urllib quietly followed them to whatever answers at the end.
        self.assertFalse(self._asked().kwargs["follow_redirects"])

    def test_the_agent_says_which_subsystem_is_knocking(self):
        agent = self._asked().kwargs["headers"]["User-Agent"]
        self.assertTrue(agent.startswith("little-sister/"))
        self.assertIn("link probe", agent)

    def test_no_body_is_read(self):
        self.assertFalse(self._asked().kwargs["read_body"])

    def test_the_request_carries_the_probe_timeout(self):
        self.assertEqual(self._asked().kwargs["timeout"],
                         link_probe.REQUEST_TIMEOUT)


class MalformedAnswerTests(TestCase):
    """A server that answers garbage costs its own verdict, not the pass.

    The *conversion* — that `BadStatusLine` and friends become a `RemoteError` at all
    — is `fetch`'s job and is tested there. What is tested here is the half this
    module owns: such a failure is **no answer**, never a death, and it is contained.
    """

    def probe(self, error):
        def request(url, method):
            raise error
        with mock.patch.object(link_probe, "_request", request):
            return link_probe._probe("https://x.example.org/", frozenset({200}))

    def test_a_garbage_answer_is_no_answer_rather_than_a_death(self):
        # `BadStatusLine` and `InvalidURL` are neither `OSError` nor `ValueError`,
        # and urllib re-raises them unwrapped out of `getresponse()`. One target
        # like that used to take down the whole sweep — and because a target with
        # no answer reads as "never asked", every later open started another one.
        for reason in (http.client.BadStatusLine("this is not http"),
                       http.client.InvalidURL("nonnumeric port"),
                       http.client.HTTPException("something else")):
            with self.subTest(error=type(reason).__name__):
                verdict = self.probe(transport_failure(reason))
                self.assertIsNone(verdict.alive)      # no idea, not "gone"
                self.assertEqual(verdict.detail, "no answer")

    @staticmethod
    def _two_targets():
        return config_with(Link(title="Good", url="https://good.example.org/",
                                check=True),
                           Link(title="Bad", url="https://bad.example.org/",
                                check=True),
                           links=True)

    def test_a_garbage_target_still_gets_a_verdict_so_it_is_not_re_probed(self):
        """The production path, and the reason the old bug was expensive: a target
        with **no** verdict reads as "never asked", so every later open started
        another doomed pass."""
        def request(url, method):
            if url == "https://good.example.org/":
                return 200
            raise transport_failure(http.client.BadStatusLine("garbage"))

        config = self._two_targets()
        with mock.patch.object(link_probe, "_request", request):
            link_probe.start_pass(config).wait(5)
        view = link_probe.page_view(config)
        self.assertEqual(len(view.verdicts), 2)
        self.assertIs(view.verdicts["https://good.example.org/"].alive, True)
        self.assertIsNone(view.verdicts["https://bad.example.org/"].alive)
        # and with every target answered, the next open is not due again
        self.assertIsNone(link_probe.refresh_if_due(config))

    def test_an_unexpected_exception_costs_only_its_own_target(self):
        """The backstop under the one above. `_probe` catches what a request is
        expected to fail with; anything else is a bug, and one target's bug must not
        cost the other fifty-nine their answers."""
        def request(url, method):
            if url == "https://good.example.org/":
                return 200
            raise RuntimeError("a bug, not a failed request")

        config = self._two_targets()
        with mock.patch.object(link_probe, "_request", request):
            link_probe.start_pass(config).wait(5)
        view = link_probe.page_view(config)
        self.assertIs(view.verdicts["https://good.example.org/"].alive, True)
        self.assertNotIn("https://bad.example.org/", view.verdicts)


class IntervalTests(TestCase):
    """`interval:` is raw text the loader does not validate, so this is the only
    place a typo can be caught — and it must fall back, not raise."""

    def test_a_readable_interval_is_used(self):
        self.assertEqual(
            link_probe._interval_seconds(config_with(interval="30m")), 1800)

    def test_an_unreadable_interval_falls_back(self):
        # `6 hours` is a plausible thing to type, and it used to take GET /links
        # to a 500 — the constant beside this has always promised a fallback
        for raw in ("6 hours", "inf", "nan", "every day"):
            with self.subTest(interval=raw):
                with self.assertLogs("little_sister", level="WARNING"):
                    seconds = link_probe._interval_seconds(
                        config_with(interval=raw))
                self.assertEqual(seconds, link_probe.DEFAULT_INTERVAL_SECONDS)

    def test_a_non_positive_interval_falls_back(self):
        # it would make every open due, which is the stampede the interval exists
        # to prevent
        for raw in ("0", "-1d"):
            with self.subTest(interval=raw):
                with self.assertLogs("little_sister", level="WARNING"):
                    self.assertEqual(
                        link_probe._interval_seconds(config_with(interval=raw)),
                        link_probe.DEFAULT_INTERVAL_SECONDS)

    def test_the_page_survives_an_unreadable_interval(self):
        config = config_with(Link(title="Wiki", url="https://x.example.org/",
                                  check=True),
                             links=True, interval="6 hours")
        with mock.patch.object(link_probe, "_request", answering(200)):
            with self.assertLogs("little_sister", level="WARNING"):
                event = link_probe.refresh_if_due(config)
        if event is not None:
            event.wait(5)


class DeadlineTests(TestCase):
    """A pass that cannot finish must end anyway (ADR-0030).

    ``REQUEST_TIMEOUT`` bounds one socket operation and not one request, so a
    server that dribbles a byte every four seconds never times out. Under the old
    shape that single host held the only pass slot for as long as it liked, and
    reachability was frozen until the instance restarted. Nothing here reaches the
    network or sleeps on a guess: every wedge is a :class:`threading.Event` the
    test owns and releases, and the deadline is shrunk to a second so the wall
    clock is not part of the assertion.
    """

    def setUp(self):
        self.held = threading.Event()
        # LIFO: held.set (registered last) runs first, so the drain below only
        # ever waits on workers that have already been released.
        self.addCleanup(self._drained)
        self.addCleanup(self.held.set)
        self.started = {}
        self.calls = []
        # The stuck count is module state, so a leftover crossing a test
        # boundary turns a deadline case into a flake: released, a wedged
        # worker exits in microseconds on an idle box — and lags past the next
        # test's assertion on a loaded one (`2 != 1`, seen live).
        self._drained(when="before")

    def _drained(self, when="after"):
        """Wait out every wedged worker still letting go of the module state."""
        if not self._eventually(lambda: link_probe.stuck_passes() == 0
                                and not link_probe.is_running()):
            self.fail(f"a wedged probe survived {when} the test "
                      f"(stuck={link_probe.stuck_passes()})")

    def wedging(self, *slow, answer=200):
        """A ``_request`` stand-in that blocks on the test's event for ``slow``.

        Records every call it was asked to make, which is how the cases below tell
        *never started* from *started and unfinished* without reading the
        executor's internals.
        """
        seen, calls = self.started, self.calls

        def request(url, method):
            calls.append((url, method))
            seen.setdefault(url, threading.Event()).set()
            if url in slow:
                self.held.wait(10)
            return answer

        return request

    def short_deadline(self, floor=1.0):
        """Shrink a pass's deadline to one readable second.

        Patched rather than passed, because the deadline is derived from the target
        count on purpose — a fixture that handed one in would stop testing the
        thing that goes wrong when sixty entries are configured.
        """
        return mock.patch.multiple(link_probe, PASS_DEADLINE_FLOOR=floor,
                                   REQUEST_TIMEOUT=0.1)

    def config_for(self, *urls):
        return config_with(*(Link(title=url, url=url, check=True) for url in urls),
                           links=True)

    # ----- storing what came back, when it came back -----

    def test_a_slow_target_does_not_hold_the_other_answers_back(self):
        # `pool.map` yields in **submission** order, so a slow first target kept
        # every later verdict out of the store until it finished — while the
        # docstring above it said "as they arrive". That is the promise a deadline
        # is built on, so it had to become true before the deadline could mean
        # anything.
        slow, quick = "https://slow.example.org/", "https://quick.example.org/"
        config = self.config_for(slow, quick)
        request = self.wedging(slow)
        with mock.patch.object(link_probe, "_request", request):
            done = link_probe.start_pass(config)
            # the quick answer lands while the slow one is still on the wire
            self.assertTrue(self._eventually(lambda: quick in link_probe.results()),
                            "the quick answer waited for the slow one")
            self.assertNotIn(slow, link_probe.results())
            self.held.set()
            self.assertTrue(done.wait(5))
        self.assertEqual(set(link_probe.results()), {slow, quick})

    def _eventually(self, predicate, timeout=5.0):
        """Wait for a condition another thread will make true.

        Only used where the thing being waited for is a *store*, which has no event
        of its own — every other wait in this file is on one the test owns.
        """
        deadline = datetime.now() + timedelta(seconds=timeout)
        while datetime.now() < deadline:
            if predicate():
                return True
            threading.Event().wait(0.01)
        return False

    # ----- the deadline itself -----

    def test_the_deadline_grows_with_the_page(self):
        # Six links and sixty are not the same sweep: `CONCURRENCY` probes run at
        # once, so the honest unit is rounds.
        self.assertEqual(link_probe._pass_deadline(1),
                         link_probe.PASS_DEADLINE_FLOOR)
        rounds = 60 / link_probe.CONCURRENCY
        self.assertEqual(link_probe._pass_deadline(60),
                         rounds * link_probe.REQUEST_TIMEOUT
                         * link_probe.PASS_DEADLINE_SLACK)

    def test_the_floor_outlasts_a_check_now(self):
        # *Check now* promises that "the pass carries on without me". A pass that
        # expired before the press it came from stopped waiting would make that
        # sentence false.
        self.assertGreater(link_probe.PASS_DEADLINE_FLOOR,
                           link_probe.CHECK_NOW_DEADLINE)

    def test_a_wedged_target_no_longer_holds_the_pass_open(self):
        # The bug: `with ThreadPoolExecutor(...)` calls `shutdown(wait=True)` on the
        # way out, so the pass could not end while a worker was wedged — and
        # `_running` was only cleared in its `finally`. One dribbling server froze
        # reachability for the life of the process.
        url = "https://wedged.example.org/"
        config = self.config_for(url)
        with self.short_deadline():
            with mock.patch.object(link_probe, "_request", self.wedging(url)):
                done = link_probe.start_pass(config)
                with self.assertLogs("little_sister", level="WARNING"):
                    self.assertTrue(done.wait(5), "the pass never ended")
                self.assertFalse(link_probe.is_running())
                # and the next pass may start, which is the whole point
                self.assertIsNot(link_probe.start_pass(config), done)
                self.held.set()

    def test_what_answered_is_kept_and_what_did_not_says_so(self):
        # Three fates, and only the middle one is new: answered keeps its verdict,
        # started-and-unfinished gets *no answer* — which is not a death, because
        # ADR-0030 §10 reserves that for a refusal or a name that does not resolve.
        slow, quick = "https://slow.example.org/", "https://quick.example.org/"
        config = self.config_for(slow, quick)
        with self.short_deadline():
            with mock.patch.object(link_probe, "_request", self.wedging(slow)):
                with self.assertLogs("little_sister", level="WARNING"):
                    self.assertTrue(link_probe.start_pass(config).wait(5))
                self.held.set()
        answers = link_probe.results()
        self.assertIs(answers[quick].alive, True)
        self.assertIsNone(answers[slow].alive)
        self.assertEqual(answers[slow].detail, "no answer in 1s")

    def test_a_target_the_pass_never_reached_keeps_what_it_had(self):
        # Canceled out of the queue means nothing was asked, so nothing is known —
        # and overwriting a good answer with *no answer* would be this module
        # inventing a failure it never observed.
        slow, later = "https://slow.example.org/", "https://later.example.org/"
        config = self.config_for(slow, later)
        with mock.patch.object(link_probe, "_request", answering(200)):
            self.assertTrue(link_probe.start_pass(config).wait(5))
        first = link_probe.results()[later]
        # one worker, so `later` is still in the queue when the deadline lands
        with self.short_deadline(), mock.patch.object(link_probe, "CONCURRENCY", 1):
            with mock.patch.object(link_probe, "_request", self.wedging(slow)):
                with self.assertLogs("little_sister", level="WARNING"):
                    self.assertTrue(link_probe.start_pass(config).wait(5))
                self.held.set()
        self.assertNotIn(later, self.started)
        self.assertEqual(link_probe.results()[later], first)
        self.assertIsNone(link_probe.results()[slow].alive)

    # ----- leftovers -----

    def test_an_abandoned_probe_is_counted_until_it_lets_go(self):
        # The count is what the page says and what the cap below counts, and a
        # leftover must stop counting the moment its socket does — not when the
        # pass that gave up on it ended, which was long before.
        url = "https://wedged.example.org/"
        config = self.config_for(url)
        with self.short_deadline():
            with mock.patch.object(link_probe, "_request", self.wedging(url)):
                with self.assertLogs("little_sister", level="WARNING"):
                    self.assertTrue(link_probe.start_pass(config).wait(5))
                self.assertEqual(link_probe.stuck_passes(), 1)
                self.assertEqual(link_probe.page_view(config).stuck, 1)
                self.held.set()
                self.assertTrue(self._eventually(
                    lambda: link_probe.stuck_passes() == 0))

    def test_enough_stuck_passes_stop_new_ones_from_starting(self):
        # Each leftover holds a worker thread and a socket the host refuses to
        # release. Probing every six hours against a target that never answers
        # would accumulate them without bound, so there is a cap — and the page
        # says so rather than looking like a button that does nothing.
        url = "https://wedged.example.org/"
        config = self.config_for(url)
        with self.short_deadline(floor=0.3):
            with mock.patch.object(link_probe, "_request", self.wedging(url)):
                for attempt in range(link_probe.MAX_STUCK_PASSES):
                    with self.subTest(attempt=attempt):
                        with self.assertLogs("little_sister", level="WARNING"):
                            self.assertTrue(link_probe.start_pass(config).wait(5))
                        self.assertEqual(link_probe.stuck_passes(), attempt + 1)
                self.assertTrue(link_probe.page_view(config).paused)
                asked = len(self.calls)
                with self.assertLogs("little_sister", level="WARNING"):
                    refused = link_probe.start_pass(config)
                # already set: the honest answer to "wait for the pass" is that
                # there is not going to be one
                self.assertTrue(refused.wait(0))
                self.assertFalse(link_probe.is_running())
                self.assertEqual(len(self.calls), asked,
                                 "a refused pass still spent a request")
                self.held.set()
                self.assertTrue(self._eventually(
                    lambda: not link_probe.page_view(config).paused))

    def test_one_leftover_is_not_an_apology(self):
        # `stuck` and `paused` are different sentences: one abandoned pass costs a
        # few threads, and only the cap means nothing is being probed at all.
        self.assertFalse(link_probe.ProbeView(active=True, stuck=1).paused)
        self.assertTrue(link_probe.ProbeView(
            active=True, stuck=link_probe.MAX_STUCK_PASSES).paused)


class GenerationTests(TestCase):
    """Abandonment means two passes can be alive at once, so one has to lose.

    Two passes writing into one store interleave into a set of answers with no
    single age, and the freshness line on the page is a single age. So a superseded
    pass stops writing, does not prune, and does not clear the slot its successor
    is using.
    """

    def a_pass(self, generation, deadline=30.0, age=0.0):
        return link_probe._Pass(generation=generation, done=threading.Event(),
                                started_at=datetime.now() - timedelta(seconds=age),
                                deadline=deadline)

    def test_a_superseded_pass_stores_nothing(self):
        stale, current = self.a_pass(1), self.a_pass(2)
        link_probe._running = current
        self.addCleanup(setattr, link_probe, "_running", None)
        verdict = link_probe.Verdict("https://a.example.org/", True, "HTTP 200",
                                     datetime.now())
        self.assertFalse(link_probe._store(stale, verdict))
        self.assertEqual(link_probe.results(), {})
        self.assertTrue(link_probe._store(current, verdict))
        self.assertEqual(set(link_probe.results()), {verdict.url})

    def test_a_superseded_pass_does_not_free_the_slot(self):
        # Otherwise its successor's `finally` would find nothing to clear, the page
        # would report no pass running while one was, and the next open would start
        # a third.
        stale, current = self.a_pass(1), self.a_pass(2)
        link_probe._running = current
        self.addCleanup(setattr, link_probe, "_running", None)
        link_probe._finish(stale)
        self.assertIs(link_probe._running, current)
        self.assertTrue(stale.done.is_set())     # whoever waited on it is told
        link_probe._finish(current)
        self.assertIsNone(link_probe._running)

    def test_a_pass_inside_its_deadline_is_joined_not_replaced(self):
        self.assertFalse(self.a_pass(1, deadline=30.0, age=5.0).overdue())

    def test_a_pass_past_its_grace_is_overdue(self):
        self.assertTrue(self.a_pass(
            1, deadline=1.0, age=1.0 + link_probe.PASS_ABANDON_GRACE + 1).overdue())

    def test_a_pass_that_stops_honoring_its_deadline_is_superseded(self):
        # A pass enforces its own deadline, so this should never fire. It is here
        # because "one wedged pass cannot freeze reachability" should be a property
        # of the structure rather than of an argument about where a thread can
        # block — so the structure is tested with the thread wedged somewhere the
        # deadline does not reach.
        config = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True), links=True)
        wedged, entered = threading.Event(), threading.Event()
        self.addCleanup(wedged.set)
        real_sweep, calls = link_probe._sweep, []

        def sweep(current, urls, alive):
            calls.append(current)
            if len(calls) == 1:
                entered.set()
                wedged.wait(10)
                return True
            return real_sweep(current, urls, alive)

        with mock.patch.multiple(link_probe, _sweep=sweep, PASS_ABANDON_GRACE=0.0), \
                mock.patch.object(link_probe, "_request", answering(200)):
            # Only the *first* pass gets the tiny deadline: the second is the one
            # that has to do real work, and a deadline measured in tenths would
            # make this a test about how busy the machine is.
            with mock.patch.multiple(link_probe, PASS_DEADLINE_FLOOR=0.1,
                                     REQUEST_TIMEOUT=0.01):
                first = link_probe.start_pass(config)
            self.assertTrue(entered.wait(5))
            threading.Event().wait(0.4)                  # let it fall past grace
            with self.assertLogs("little_sister", level="WARNING"):
                second = link_probe.start_pass(config)
            self.assertIsNot(second, first)
            self.assertTrue(second.wait(5))
            self.assertEqual(set(link_probe.results()), {"https://a.example.org/"})
            # the slot is the second pass's, and the first must not free it
            self.assertIsNone(link_probe._running)
            wedged.set()
            self.assertTrue(first.wait(5))
        self.assertEqual(len(calls), 2)

    def test_a_press_does_not_join_a_pass_that_has_given_up_the_ghost(self):
        # Joining a pass that has stopped honoring its own deadline is joining
        # nothing, and the forced-pass gap does not apply either: the gap exists to
        # stop a reader spending requests on answers that are seconds old, and
        # these are not going to arrive at all.
        config = config_with(Link(title="A", url="https://a.example.org/",
                                  check=True), links=True)
        link_probe._running = self.a_pass(99, deadline=0.1, age=60.0)
        self.addCleanup(setattr, link_probe, "_running", None)
        with mock.patch.multiple(link_probe, PASS_ABANDON_GRACE=0.0):
            with mock.patch.object(link_probe, "_request", answering(200)):
                with self.assertLogs("little_sister", level="WARNING"):
                    self.assertTrue(link_probe.refresh_now(config, deadline=5))
        self.assertEqual(set(link_probe.results()), {"https://a.example.org/"})
