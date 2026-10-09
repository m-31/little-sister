"""The assembled Content-Security-Policy (ADR-0048).

The header is a *value*, which is the property this file leans on: what a browser
would be told can be asserted without a browser — the defaults are present, a
contributed origin is accepted, a contributed keyword is refused, a configured source
is added.
"""
import re
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import TestCase

from little_sister import csp
from little_sister.config_dir import forget_aspects, register_aspect

CDN = "https://cdn.jsdelivr.net"
TRACKER = "https://tickets.example.org"
#: The library's own img-src: no host, and data:, which calls none.
FLOOR_IMG = ("'self'", "data:")


@contextmanager
def _roots(*documents: str):
    """One configuration root per ``documents`` entry, each holding that text as its
    ``csp.yaml`` (an empty string writes no file at all). Yields the path-list."""
    with tempfile.TemporaryDirectory() as parent:
        roots = []
        for index, text in enumerate(documents):
            root = Path(parent) / f"root{index}"
            root.mkdir()
            if text:
                (root / "csp.yaml").write_text(text, encoding="utf-8")
            roots.append(str(root))
        yield ":".join(roots) if roots else str(Path(parent))


@contextmanager
def _aspect_root(name, text):
    """A root carrying ``<name>.yaml`` for a **registered** aspect — what
    :func:`csp.origin_of` reads a deployment-specific host out of."""
    register_aspect(name)
    with tempfile.TemporaryDirectory() as root:
        (Path(root) / f"{name}.yaml").write_text(text, encoding="utf-8")
        try:
            yield str(root)
        finally:
            forget_aspects()


class DefaultsTests(TestCase):
    """The library's own floor: what our pages need, and nothing else."""

    def test_the_defaults_are_in_the_header(self):
        with _roots() as roots:
            header = csp.assemble(config_dir=roots).header()
        self.assertIn("default-src 'self'", header)
        self.assertIn(f"script-src 'self' {CDN}", header)
        self.assertIn("object-src 'none'", header)
        self.assertIn(f"report-uri {csp.REPORT_PATH}", header)

    def test_style_src_keeps_unsafe_inline_and_img_src_names_no_host(self):
        # the two deliberate asymmetries: a computed style= cannot be hashed even in
        # principle, while img-src is the directive with something to measure — so it
        # names no host, and takes data:, which calls none: Bootstrap draws a switch's
        # knob and the bar's burger as data: images
        with _roots() as roots:
            policy = csp.assemble(config_dir=roots)
        self.assertIn("'unsafe-inline'", policy.sources_of("style-src"))
        self.assertEqual(policy.sources_of("img-src"), ("'self'", "data:"))

    def test_every_default_source_is_attributed_to_the_library(self):
        with _roots() as roots:
            policy = csp.assemble(config_dir=roots)
        contributors = {source.by for _, sources in policy.directives
                        for source in sources}
        self.assertEqual(contributors, {csp.LIBRARY})

    def test_an_inline_script_becomes_a_hash_in_script_src(self):
        with _roots() as roots:
            policy = csp.assemble(inline_scripts=("alert(1)",), config_dir=roots)
        self.assertIn(csp.inline_hash("alert(1)"), policy.sources_of("script-src"))

    def test_the_hash_is_the_base64_sha256_a_browser_computes(self):
        # the well-known digest of the empty string, so a wrong encoding shows here
        self.assertEqual(
            csp.inline_hash(""),
            "'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='")

    def test_the_policy_is_assembled_late_not_constant(self):
        # the whole decision in one assertion: the same call returns a wider policy
        # after a registration, because there is no constant to have been captured
        with _roots() as roots:
            before = csp.assemble(config_dir=roots).sources_of("connect-src")
            csp.allow("connect-src", TRACKER, by="ls_tickets")
            after = csp.assemble(config_dir=roots).sources_of("connect-src")
        self.assertEqual(before, ("'self'",))
        self.assertEqual(after, ("'self'", TRACKER))


class ContributionTests(TestCase):
    """What a dependent package may add, and what it may not."""

    def test_an_origin_is_accepted_and_attributed(self):
        csp.allow("connect-src", TRACKER, by="ls_tickets")
        with _roots() as roots:
            policy = csp.assemble(config_dir=roots)
        added = [source for _, sources in policy.directives for source in sources
                 if source.value == TRACKER]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].by, "ls_tickets")

    def test_an_origin_with_a_port_is_accepted(self):
        csp.allow("img-src", "https://assets.example.org:8443", by="pkg")
        self.assertEqual(len(csp.contributions()), 1)

    def test_a_keyword_is_refused(self):
        # decision 3: a dependency able to relax the policy makes it decorative for
        # every other package in the process
        for keyword in ("'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'",
                        "'self'", "'none'"):
            with self.subTest(keyword=keyword):
                with self.assertLogs("little_sister", level="WARNING") as logs:
                    csp.allow("script-src", keyword, by="pkg")
                self.assertEqual(csp.contributions(), ())
                self.assertIn("never a keyword", "\n".join(logs.output))

    def test_a_wildcard_or_a_bare_scheme_is_refused(self):
        for source in ("*", "https:", "data:"):
            with self.subTest(source=source):
                with self.assertLogs("little_sister", level="WARNING"):
                    csp.allow("img-src", source, by="pkg")
                self.assertEqual(csp.contributions(), ())

    def test_a_source_that_is_not_one_token_is_refused(self):
        # the severe one: a policy separates sources by whitespace and directives by
        # `;`, so a "source" holding either would let a dependency append directives of
        # its own — and CSP honors the *first* occurrence of a directive, so an
        # injected one placed early wins over the library's
        for source in ("https://a.example 'unsafe-inline'",
                       "https://a.example; script-src 'unsafe-inline'",
                       "https://a.example\t*",
                       "https://a.example,https://b.example",
                       "https://a.example\nX-Evil: 1"):
            with self.subTest(source=source):
                with self.assertLogs("little_sister", level="WARNING") as logs:
                    csp.allow("script-src", source, by="pkg")
                self.assertEqual(csp.contributions(), ())
                self.assertIn("not a single source", "\n".join(logs.output))

    def test_an_injected_directive_never_reaches_the_header(self):
        csp.allow("script-src", "https://x.example; img-src *", by="pkg")
        csp.allow("img-src", "https://*", by="pkg")
        with _roots() as roots:
            header = csp.assemble(config_dir=roots).header()
        self.assertEqual(header.count("img-src"), 1)
        self.assertNotIn("*", header)
        self.assertNotIn("https://x.example", header)

    def test_a_wildcard_host_is_refused_from_a_package(self):
        for source in ("https://*", "https://*.example.org", "https://a.example:*"):
            with self.subTest(source=source):
                with self.assertLogs("little_sister", level="WARNING") as logs:
                    csp.allow("img-src", source, by="pkg")
                self.assertEqual(csp.contributions(), ())
                self.assertIn("wildcard", "\n".join(logs.output))

    def test_only_a_scheme_a_browser_fetches_over_is_an_origin(self):
        for source in ("javascript://a.example", "file://a.example",
                       "gopher://a.example"):
            with self.subTest(source=source):
                with self.assertLogs("little_sister", level="WARNING"):
                    csp.allow("script-src", source, by="pkg")
                self.assertEqual(csp.contributions(), ())

    def test_an_origin_is_stored_lower_cased(self):
        # a scheme and host are case-insensitive to a browser, so this is accepted —
        # but canonicalized, or two packages naming one host differently would put two
        # entries in the policy
        csp.allow("img-src", "HTTPS://A.Example", by="one")
        csp.allow("img-src", "https://a.example", by="two")
        with _roots() as roots:
            self.assertEqual(csp.assemble(config_dir=roots).sources_of("img-src"),
                             (*FLOOR_IMG, "https://a.example"))

    def test_an_ipv6_literal_keeps_its_brackets(self):
        csp.allow("connect-src", "https://[2001:db8::1]:8443", by="pkg")
        with _roots() as roots:
            self.assertIn("https://[2001:db8::1]:8443",
                          csp.assemble(config_dir=roots).sources_of("connect-src"))

    def test_an_unparsable_port_is_refused(self):
        with self.assertLogs("little_sister", level="WARNING"):
            csp.allow("connect-src", "https://a.example:notaport", by="pkg")
        self.assertEqual(csp.contributions(), ())

    def test_a_source_carrying_credentials_is_refused(self):
        with self.assertLogs("little_sister", level="WARNING"):
            csp.allow("connect-src", "https://user:pw@a.example", by="pkg")
        self.assertEqual(csp.contributions(), ())

    def test_a_source_carrying_a_path_is_refused_and_the_origin_named(self):
        with self.assertLogs("little_sister", level="WARNING") as logs:
            csp.allow("connect-src", "https://tickets.example.org/api/v2", by="pkg")
        self.assertEqual(csp.contributions(), ())
        self.assertIn("https://tickets.example.org", "\n".join(logs.output))

    def test_something_that_is_not_an_origin_at_all_is_refused(self):
        for source in ("tickets.example.org", "", "not a url"):
            with self.subTest(source=source):
                with self.assertLogs("little_sister", level="WARNING"):
                    csp.allow("connect-src", source, by="pkg")
                self.assertEqual(csp.contributions(), ())

    def test_an_unknown_directive_is_refused_with_the_roster(self):
        with self.assertLogs("little_sister", level="WARNING") as logs:
            csp.allow("frame-src", TRACKER, by="pkg")
        self.assertEqual(csp.contributions(), ())
        self.assertIn("connect-src", "\n".join(logs.output))

    def test_a_directive_the_library_keeps_to_itself_is_refused(self):
        # widening default-src widens every directive that falls back to it
        for directive in ("default-src", "base-uri", "object-src", "report-uri"):
            with self.subTest(directive=directive):
                with self.assertLogs("little_sister", level="WARNING") as logs:
                    csp.allow(directive, TRACKER, by="pkg")
                self.assertEqual(csp.contributions(), ())
                self.assertIn("keeps to itself", "\n".join(logs.output))

    def test_a_contribution_without_a_contributor_is_refused(self):
        with self.assertLogs("little_sister", level="WARNING"):
            csp.allow("connect-src", TRACKER, by="  ")
        self.assertEqual(csp.contributions(), ())

    def test_a_repeated_contribution_is_recorded_once(self):
        csp.allow("connect-src", TRACKER, by="pkg")
        csp.allow("connect-src", TRACKER, by="pkg")
        self.assertEqual(len(csp.contributions()), 1)

    def test_two_packages_may_ask_for_the_same_origin(self):
        # both are recorded (each is answerable for its own need) and the policy
        # names the origin once
        csp.allow("connect-src", TRACKER, by="one")
        csp.allow("connect-src", TRACKER, by="two")
        self.assertEqual(len(csp.contributions()), 2)
        with _roots() as roots:
            self.assertEqual(csp.assemble(config_dir=roots).sources_of("connect-src"),
                             ("'self'", TRACKER))

    def test_contributing_a_source_the_defaults_already_have_changes_nothing(self):
        csp.allow("script-src", CDN, by="pkg")
        with _roots() as roots:
            self.assertEqual(csp.assemble(config_dir=roots).sources_of("script-src"),
                             ("'self'", CDN))


class OriginOfTests(TestCase):
    """A deployment-specific host is declared, not written (decision 4)."""

    def test_credentials_in_the_field_are_dropped_not_carried(self):
        # a base_url an operator wrote for their own purposes may hold basic-auth
        # credentials; they are not part of an origin and must never reach a header
        document = "base_url: https://svc:s3cr3t@jira.example.org/rest\n"
        with _aspect_root("tickets", document) as root:
            csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="pkg")
            policy = csp.assemble(config_dir=root)
        self.assertEqual(policy.sources_of("connect-src"),
                         ("'self'", "https://jira.example.org"))
        self.assertNotIn("s3cr3t", policy.header())

    def test_a_reference_is_resolved_and_reduced_to_its_origin(self):
        document = "base_url: https://jira.example.org/rest/api/2?x=1\n"
        with _aspect_root("tickets", document) as root:
            csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="pkg")
            with self.assertNoLogs("little_sister", level="WARNING"):
                policy = csp.assemble(config_dir=root)
        self.assertEqual(policy.sources_of("connect-src"),
                         ("'self'", "https://jira.example.org"))

    def test_a_port_survives_the_reduction(self):
        document = "base_url: https://jira.example.org:8443/x\n"
        with _aspect_root("tickets", document) as r:
            csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="pkg")
            policy = csp.assemble(config_dir=r)
        self.assertIn("https://jira.example.org:8443",
                      policy.sources_of("connect-src"))

    def test_a_dotted_field_reaches_one_level_down(self):
        document = "api:\n  base_url: https://a.example.org/v2\n"
        with _aspect_root("tickets", document) as r:
            csp.allow("img-src", csp.origin_of("tickets.api.base_url"), by="pkg")
            policy = csp.assemble(config_dir=r)
        self.assertIn("https://a.example.org", policy.sources_of("img-src"))

    def test_a_later_root_wins_the_field(self):
        register_aspect("tickets")
        with tempfile.TemporaryDirectory() as parent:
            base, site = Path(parent) / "base", Path(parent) / "site"
            base.mkdir()
            site.mkdir()
            (base / "tickets.yaml").write_text("base_url: https://base.example.org\n")
            (site / "tickets.yaml").write_text("base_url: https://site.example.org\n")
            csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="pkg")
            policy = csp.assemble(config_dir=f"{base}:{site}")
        forget_aspects()
        self.assertIn("https://site.example.org", policy.sources_of("connect-src"))
        self.assertNotIn("https://base.example.org", policy.sources_of("connect-src"))

    def test_an_unregistered_aspect_warns_and_adds_nothing(self):
        csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="pkg")
        with _roots() as roots, \
                self.assertLogs("little_sister", level="WARNING") as logs:
            policy = csp.assemble(config_dir=roots)
        self.assertEqual(policy.sources_of("connect-src"), ("'self'",))
        self.assertIn("not a registered configuration aspect", "\n".join(logs.output))

    def test_a_missing_field_warns_and_adds_nothing(self):
        with _aspect_root("tickets", "project: PLAT\n") as root:
            csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="pkg")
            with self.assertLogs("little_sister", level="WARNING"):
                policy = csp.assemble(config_dir=root)
        self.assertEqual(policy.sources_of("connect-src"), ("'self'",))

    def test_a_field_that_is_not_a_url_warns_and_adds_nothing(self):
        with _aspect_root("tickets", "base_url: jira.example.org\n") as root:
            csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="pkg")
            with self.assertLogs("little_sister", level="WARNING"):
                policy = csp.assemble(config_dir=root)
        self.assertEqual(policy.sources_of("connect-src"), ("'self'",))

    def test_a_malformed_reference_warns_and_adds_nothing(self):
        for reference in ("tickets", "", "../etc/passwd"):
            with self.subTest(reference=reference):
                csp.forget_contributions()
                csp.allow("connect-src", csp.origin_of(reference), by="pkg")
                with _roots() as roots, \
                        self.assertLogs("little_sister", level="WARNING"):
                    policy = csp.assemble(config_dir=roots)
                self.assertEqual(policy.sources_of("connect-src"), ("'self'",))


class ConfiguredTests(TestCase):
    """The deployment's last word (decision 5) — and the one place a keyword lands."""

    def test_a_configured_origin_joins_the_policy_and_names_its_file(self):
        with _roots(f"img-src:\n  - {TRACKER}\n") as roots:
            policy = csp.assemble(config_dir=roots)
        sources = dict(policy.directives)["img-src"]
        self.assertEqual(tuple(s.value for s in sources), (*FLOOR_IMG, TRACKER))
        self.assertTrue(sources[-1].by.endswith("csp.yaml"))

    def test_a_keyword_is_taken_here(self):
        with _roots("script-src:\n  - \"'unsafe-inline'\"\n") as roots:
            policy = csp.assemble(config_dir=roots)
        self.assertIn("'unsafe-inline'", policy.sources_of("script-src"))

    def test_a_configured_source_that_is_not_one_token_is_refused(self):
        # the same injection, from the other side — and the newline case is the one
        # that would otherwise make the header unassignable and 500 every page
        document = ('img-src:\n  - "https://a.example; object-src *"\n'
                    '  - "https://b.example\\nX-Evil: 1"\n')
        with _roots(document) as roots, \
                self.assertLogs("little_sister", level="WARNING") as logs:
            policy = csp.assemble(config_dir=roots)
        self.assertEqual(policy.sources_of("img-src"), FLOOR_IMG)
        self.assertIn("not a single source", "\n".join(logs.output))
        self.assertNotIn("\n", policy.header())

    def test_a_wildcard_subdomain_is_taken_here(self):
        # not an origin, so a package may not write one, but a legitimate source
        with _roots("img-src:\n  - https://*.example.org\n") as roots:
            self.assertIn("https://*.example.org",
                          csp.assemble(config_dir=roots).sources_of("img-src"))

    def test_configured_none_is_refused_because_the_file_only_adds(self):
        # it reads like locking the directive down and cannot be: a configured source
        # is added, and 'none' means anything only when it is alone
        with _roots("img-src:\n  - \"'none'\"\n") as roots, \
                self.assertLogs("little_sister", level="WARNING") as logs:
            policy = csp.assemble(config_dir=roots)
        self.assertEqual(policy.sources_of("img-src"), FLOOR_IMG)
        self.assertIn("only means anything", "\n".join(logs.output))

    def test_a_bare_scheme_and_a_wildcard_are_taken_here(self):
        with _roots("img-src:\n  - \"blob:\"\n  - \"*\"\n") as roots:
            self.assertEqual(csp.assemble(config_dir=roots).sources_of("img-src"),
                             (*FLOOR_IMG, "blob:", "*"))

    def test_one_bare_source_needs_no_list(self):
        with _roots(f"connect-src: {TRACKER}\n") as roots:
            self.assertIn(TRACKER,
                          csp.assemble(config_dir=roots).sources_of("connect-src"))

    def test_roots_union_rather_than_replace(self):
        with _roots("img-src:\n  - https://a.example.org\n",
                    "img-src:\n  - https://b.example.org\n") as roots:
            self.assertEqual(csp.assemble(config_dir=roots).sources_of("img-src"),
                             (*FLOOR_IMG, "https://a.example.org",
                              "https://b.example.org"))

    def test_a_directive_the_library_does_not_emit_is_refused(self):
        with _roots("frame-src:\n  - https://a.example.org\n") as roots, \
                self.assertLogs("little_sister", level="WARNING") as logs:
            policy = csp.assemble(config_dir=roots)
        self.assertEqual(policy.sources_of("frame-src"), ())
        self.assertIn("does not emit", "\n".join(logs.output))

    def test_a_source_that_is_neither_origin_nor_keyword_is_refused(self):
        # an unknown keyword, something that is not a string, and a bare host with
        # no scheme — a typo in a policy is a policy that quietly does not do what
        # its author read
        document = "img-src:\n  - \"'wat'\"\n  - 12\n  - assets.example.org\n"
        with _roots(document) as roots, \
                self.assertLogs("little_sister", level="WARNING") as logs:
            policy = csp.assemble(config_dir=roots)
        self.assertEqual(policy.sources_of("img-src"), FLOOR_IMG)
        self.assertIn("neither an origin nor a keyword", "\n".join(logs.output))

    def test_unparsable_yaml_is_a_warning_and_not_a_dead_instance(self):
        with _roots("img-src: [unclosed\n") as roots, \
                self.assertLogs("little_sister", level="WARNING") as logs:
            policy = csp.assemble(config_dir=roots)
        self.assertEqual(policy.sources_of("img-src"), FLOOR_IMG)
        self.assertIn("could not be read", "\n".join(logs.output))

    def test_a_directive_holding_neither_a_source_nor_a_list_adds_nothing(self):
        with _roots("img-src:\n  host: https://a.example.org\n") as roots:
            self.assertEqual(csp.assemble(config_dir=roots).sources_of("img-src"),
                             FLOOR_IMG)

    def test_a_reference_into_a_field_that_is_not_a_mapping_adds_nothing(self):
        # `tickets.base_url.host` where base_url is a string: the walk stops rather
        # than raising
        with _aspect_root("tickets", "base_url: https://a.example.org\n") as root:
            csp.allow("img-src", csp.origin_of("tickets.base_url.host"), by="pkg")
            with self.assertLogs("little_sister", level="WARNING"):
                policy = csp.assemble(config_dir=root)
        self.assertEqual(policy.sources_of("img-src"), FLOOR_IMG)

    def test_a_file_that_is_not_a_mapping_is_ignored_with_a_warning(self):
        with _roots("- https://a.example.org\n") as roots, \
                self.assertLogs("little_sister", level="WARNING") as logs:
            policy = csp.assemble(config_dir=roots)
        self.assertEqual(policy.sources_of("img-src"), FLOOR_IMG)
        self.assertIn("not a mapping", "\n".join(logs.output))

    def test_an_empty_or_absent_file_is_normal_and_silent(self):
        for text in ("", "# nothing but a comment\n"):
            with self.subTest(text=text):
                with _roots(text) as roots:
                    with self.assertNoLogs("little_sister", level="WARNING"):
                        policy = csp.assemble(config_dir=roots)
                self.assertEqual(policy.sources_of("img-src"), FLOOR_IMG)

    def test_configuring_object_src_drops_the_lone_none_and_says_so(self):
        # 'none' beside another source is not a narrower policy, it is an invalid one —
        # and the directive is now *wider* than the default, which is worth a warning
        with _roots("object-src:\n  - https://a.example.org\n") as roots, \
                self.assertLogs("little_sister", level="WARNING") as logs:
            policy = csp.assemble(config_dir=roots)
        self.assertEqual(policy.sources_of("object-src"), ("https://a.example.org",))
        self.assertIn("now *wider*", "\n".join(logs.output))

    def test_only_report_uri_takes_a_bare_path(self):
        # a path is a source only for the one directive whose value is a path
        with _roots("report-uri:\n  - /elsewhere\n") as roots:
            self.assertEqual(csp.assemble(config_dir=roots).sources_of("report-uri"),
                             (csp.REPORT_PATH, "/elsewhere"))
        with _roots("img-src:\n  - /local/images\n") as roots, \
                self.assertLogs("little_sister", level="WARNING"):
            self.assertEqual(csp.assemble(config_dir=roots).sources_of("img-src"),
                             FLOOR_IMG)

    def test_the_repos_own_example_file_is_inert(self):
        # config/csp.yaml ships as documentation; it must add nothing as it stands
        root = Path(__file__).resolve().parent.parent / "config"
        policy = csp.assemble(config_dir=str(root))
        self.assertEqual(policy.sources_of("img-src"), FLOOR_IMG)
        self.assertEqual(policy.sources_of("script-src"), ("'self'", CDN))


class PageSourcesTests(TestCase):
    """What a page names for itself — the hosts ``/links`` loads its icons from,
    taken from the URLs ``links.yaml`` holds (ADR-0030, ADR-0048)."""

    def values(self, *urls):
        return [source.value for source in csp.page_sources(urls, by="links.yaml")]

    def test_a_url_becomes_the_origin_it_is_fetched_from(self):
        self.assertEqual(self.values("https://Chef.Example.org/tool/x.ico?v=1#top"),
                         ["https://chef.example.org"])

    def test_a_port_stays_and_credentials_never_reach_the_header(self):
        self.assertEqual(self.values("https://user:secret@a.example.org:8443/p"),
                         ["https://a.example.org:8443"])

    def test_an_address_is_an_origin_as_a_name_is(self):
        # a home network's links are addresses as often as names, and Chromium
        # matches an address source as it matches a host
        self.assertEqual(self.values("http://192.168.1.10:5000/favicon.ico",
                                     "http://[fd00::1]/favicon.ico"),
                         ["http://192.168.1.10:5000", "http://[fd00::1]"])

    def test_each_origin_once_in_the_order_the_page_has_them(self):
        self.assertEqual(self.values("https://b.example.org/favicon.ico",
                                     "https://a.example.org/x.svg",
                                     "https://b.example.org/other.png"),
                         ["https://b.example.org", "https://a.example.org"])

    def test_what_names_no_origin_is_skipped_and_cannot_widen_the_header(self):
        self.assertEqual(self.values("javascript:alert(1)", "file:///etc/passwd",
                                     "not a url", "https://a.example.org; script-src *",
                                     "https://a b.example.org/"), [])

    def test_every_source_answers_to_the_file_that_named_it(self):
        sources = csp.page_sources(["https://a.example.org/x"], by="config/links.yaml")
        self.assertEqual(sources, (csp.Source("https://a.example.org",
                                              "config/links.yaml"),))


class PolicyAddingTests(TestCase):
    """A page's own sources, on that page's copy of the policy (ADR-0048)."""

    def setUp(self):
        with _roots() as roots:
            self.policy = csp.assemble(config_dir=roots)
        self.page = [csp.Source("https://chef.example.org", "links.yaml")]

    def test_the_page_adds_to_its_copy_and_the_assembled_policy_stays_as_it_was(self):
        widened = self.policy.adding("img-src", self.page)
        self.assertEqual(widened.sources_of("img-src"),
                         ("'self'", "data:", "https://chef.example.org"))
        self.assertEqual(self.policy.sources_of("img-src"), ("'self'", "data:"))
        self.assertIn("img-src 'self' data: https://chef.example.org",
                      widened.header())

    def test_the_other_directives_are_untouched(self):
        widened = self.policy.adding("img-src", self.page)
        for directive, _ in self.policy.directives:
            if directive != "img-src":
                with self.subTest(directive=directive):
                    self.assertEqual(widened.sources_of(directive),
                                     self.policy.sources_of(directive))

    def test_a_source_the_directive_holds_is_not_repeated(self):
        widened = self.policy.adding("img-src", [*self.page, *self.page,
                                                 csp.Source("'self'", "links.yaml")])
        self.assertEqual(widened.sources_of("img-src"),
                         ("'self'", "data:", "https://chef.example.org"))

    def test_an_added_source_keeps_who_named_it(self):
        widened = self.policy.adding("img-src", self.page)
        added = dict(widened.directives)["img-src"][-1]
        self.assertEqual(added.by, "links.yaml")

    def test_a_directive_the_policy_lacks_is_added_with_the_sources(self):
        # an assembled policy carries every directive a page may add to; one built
        # by hand need not, and gains the directive rather than losing the sources
        bare = csp.Policy(directives=(
            ("default-src", (csp.Source("'self'", csp.LIBRARY),)),))
        self.assertEqual(bare.adding("img-src", self.page).header(),
                         "default-src 'self'; img-src https://chef.example.org")

    def test_nothing_to_add_is_the_assembled_policy_itself(self):
        self.assertIs(self.policy.adding("img-src", ()), self.policy)

    def test_a_directive_the_library_keeps_to_itself_takes_nothing(self):
        with self.assertRaises(ValueError):
            self.policy.adding("object-src", self.page)


class TemplateSurfaceTests(TestCase):
    """What the pages must not contain for a strict policy to stay reachable.

    Neither of these is about the header. They pin the two cleanups the header was
    worth doing after: an inline handler takes no hash and no nonce, and a duplicated
    inline script costs a second hash forever.
    """

    TEMPLATES = Path(__file__).resolve().parent.parent / "src" / "little_sister" \
        / "templates"

    def test_no_template_carries_an_inline_event_handler(self):
        handler = re.compile(r"\son[a-z]+\s*=\s*[\"']")
        offenders = sorted(path.name for path in self.TEMPLATES.glob("*.html")
                           if handler.search(path.read_text(encoding="utf-8")))
        self.assertEqual(offenders, [], "an inline handler takes neither a hash nor "
                                       "a nonce — wire it in a script instead")

    def test_the_only_inline_script_in_any_template_is_the_hashed_one(self):
        # the policy hashes exactly one inline script; a second one added anywhere
        # would be reported on every page view, silently and forever
        bare = re.compile(r"<script\s*>")
        carriers = sorted(path.name for path in self.TEMPLATES.glob("*.html")
                          if bare.search(path.read_text(encoding="utf-8")))
        self.assertEqual(carriers, ["_theme_bootstrap.html"])

    def test_the_theme_bootstrap_is_written_in_exactly_one_place(self):
        # one inline script means one hash; two copies of it meant two, forever
        carriers = sorted(path.name for path in self.TEMPLATES.glob("*.html")
                          if "prefers-color-scheme: dark)" in
                          path.read_text(encoding="utf-8"))
        self.assertEqual(carriers, ["_theme_bootstrap.html"])

    def test_every_document_without_a_header_includes_it(self):
        # The header carries it for every page that has one. The pages that have no
        # header are the ones somebody sees before there is a session to build one
        # from — the login form, and the door chooser that may stand in front of it
        # (ADR-0069 §1) — and each of those has to include the partial itself. The
        # one hash is what makes that cheap; two hand-written copies were what made
        # it expensive, which is the claim above.
        including = sorted(path.name for path in self.TEMPLATES.glob("*.html")
                           if "_theme_bootstrap.html" in
                           path.read_text(encoding="utf-8"))
        self.assertEqual(including,
                         ["_header.html", "choose_door.html", "login.html"])


if __name__ == "__main__":
    unittest.main()
