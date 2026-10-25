import os
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

from little_sister.config_dir import ASPECTS, aspect_in
from little_sister.icons import BUILTIN_PACKAGE, Icon, IconFile
from little_sister.links import (
    Group,
    Link,
    LinksConfig,
    current_links,
    favicon_url,
    forget_cached_links,
    links_policy_sources,
    load_links,
)

SIMPLE = """
groups:
  - title: Toolbox
    links:
      - title: Cyber Chef
        url: https://gchq.github.io/CyberChef/
        icon: sonar
        note: offline-capable, safe for production data
      - title: Grafana
        url: https://grafana.example.org/
        icon: grafana
"""


def write(directory, text, name="links.yaml"):
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def problems_matching(config, needle):
    return [problem for problem in config.problems if needle in problem]


class LoadLinksTests(TestCase):
    def test_absent_aspect_is_an_empty_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_links(Path(directory))
            self.assertEqual(config.groups, ())
            self.assertEqual(config.problems, ())
            self.assertTrue(config.is_empty())

    def test_reads_groups_entries_and_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, SIMPLE)
            config = load_links(Path(directory))
            self.assertEqual(config.problems, ())
            self.assertEqual(len(config.groups), 1)
            group = config.groups[0]
            self.assertEqual(group.title, "Toolbox")
            self.assertEqual(group.links[0], Link(
                title="Cyber Chef", url="https://gchq.github.io/CyberChef/",
                icon="sonar",
                note="offline-capable, safe for production data"))
            self.assertFalse(config.is_empty())

    def test_entry_order_is_never_sorted(self):
        # An operator who puts EMERGENCY STOP first means it (ADR-0030).
        with tempfile.TemporaryDirectory() as directory:
            write(directory, """
groups:
  - title: Loadtest Live
    links:
      - {title: EMERGENCY STOP, url: 'https://stop.example.org/'}
      - {title: Console, url: 'https://console.example.org/'}
""")
            groups = load_links(Path(directory)).groups
            self.assertEqual([link.title for link in groups[0].links],
                             ["EMERGENCY STOP", "Console"])

    def test_group_without_a_title_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - links: []\n")
            config = load_links(Path(directory))
            self.assertEqual(config.groups, ())
            self.assertTrue(problems_matching(config, "needs a title"))

    def test_group_kept_when_it_has_no_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: Empty\n")
            config = load_links(Path(directory))
            self.assertEqual(config.groups, (Group(title="Empty"),))
            self.assertTrue(config.is_empty())


class LayeringTests(TestCase):
    def test_same_title_concatenates_base_first(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write(d1, "groups:\n  - title: Toolbox\n    links:\n"
                      "      - {title: Base, url: 'https://base.example.org/'}\n")
            write(d2, "groups:\n  - title: Toolbox\n    links:\n"
                      "      - {title: Site, url: 'https://site.example.org/'}\n")
            config = load_links(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(len(config.groups), 1)
            self.assertEqual([link.title for link in config.groups[0].links],
                             ["Base", "Site"])

    def test_a_new_title_is_appended_in_path_list_order(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write(d1, "groups:\n  - title: Base only\n")
            write(d2, "groups:\n  - title: Site only\n")
            config = load_links(f"{d1}{os.pathsep}{d2}")
            self.assertEqual([group.title for group in config.groups],
                             ["Base only", "Site only"])

    def test_one_broken_layer_costs_only_its_own_entries(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write(d1, "groups: [not a mapping]\n")
            write(d2, "groups:\n  - title: Site\n    links:\n"
                      "      - {title: Site, url: 'https://site.example.org/'}\n")
            config = load_links(f"{d1}{os.pathsep}{d2}")
            self.assertEqual([group.title for group in config.groups], ["Site"])
            self.assertTrue(problems_matching(config, "expected a mapping"))

    def test_invalid_yaml_is_a_problem_not_a_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups: [\n")
            config = load_links(Path(directory))
            self.assertEqual(config.groups, ())
            self.assertTrue(problems_matching(config, "unreadable"))

    def test_sources_name_every_document_read(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write(d1, SIMPLE)
            write(d2, SIMPLE)
            config = load_links(f"{d1}{os.pathsep}{d2}")
            self.assertEqual([str(path.parent) for path in config.sources], [d1, d2])


class ValidationTests(TestCase):
    def test_unknown_top_level_key_is_named(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "grups: []\n")
            config = load_links(Path(directory))
            self.assertTrue(problems_matching(config, "unknown key(s) grups"))

    def test_unknown_entry_key_is_named(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: T\n    links:\n"
                             "      - {title: A, url: 'https://a.example.org/',"
                             " ikon: grafana}\n")
            config = load_links(Path(directory))
            self.assertTrue(problems_matching(config, "unknown key(s) ikon"))

    def test_a_rejected_scheme_drops_the_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: T\n    links:\n"
                             "      - {title: Bad, url: 'javascript:alert(1)'}\n"
                             "      - {title: Good, url: 'http://ok.example.org/'}\n")
            config = load_links(Path(directory))
            self.assertEqual([link.title for link in config.groups[0].links],
                             ["Good"])
            self.assertTrue(problems_matching(config, "will not render"))

    def test_an_entry_needs_a_title_and_a_url(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: T\n    links:\n"
                             "      - {title: No url}\n"
                             "      - {url: 'https://no.example.org/'}\n")
            config = load_links(Path(directory))
            self.assertEqual(config.groups[0].links, ())
            self.assertEqual(len(problems_matching(config, "both a title and a url")),
                             2)

    def test_duplicate_titles_are_reported_and_both_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: T\n    links:\n"
                             "      - {title: Same, url: 'https://a.example.org/'}\n"
                             "      - {title: Same, url: 'https://b.example.org/'}\n")
            config = load_links(Path(directory))
            self.assertEqual(len(config.groups[0].links), 2)
            self.assertTrue(problems_matching(config, "appears more than once"))

    def test_an_empty_document_is_not_a_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "# nothing here yet\n")
            config = load_links(Path(directory))
            self.assertEqual(config.groups, ())
            self.assertEqual(config.problems, ())

    def test_a_top_level_list_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "- Toolbox\n")
            config = load_links(Path(directory))
            self.assertTrue(problems_matching(config, "must be a mapping, got list"))

    def test_an_entry_that_is_not_a_mapping_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: T\n    links:\n"
                             "      - https://bare.example.org/\n")
            config = load_links(Path(directory))
            self.assertEqual(config.groups[0].links, ())
            self.assertTrue(problems_matching(config, "expected a mapping, got str"))

    def test_links_must_be_a_list(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: T\n    links: nope\n")
            config = load_links(Path(directory))
            self.assertEqual(config.groups[0].links, ())
            self.assertTrue(problems_matching(config, "expected a list"))


class IconMapTests(TestCase):
    def test_single_file_serves_both_backgrounds_and_is_not_a_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="icons/phoenix.svg")
            write(directory, "icons:\n  phoenix: icons/phoenix.svg\n")
            icon = load_links(Path(directory)).icons["phoenix"]
            self.assertFalse(icon.paired)
            self.assertEqual(icon.on_light, icon.on_dark)
            self.assertEqual(icon.on_light.path.name, "phoenix.svg")

    def test_a_declared_pair_is_paired(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="icons/b.svg")
            write(directory, "<svg/>", name="icons/b-inverted.svg")
            write(directory, "icons:\n  backstage:\n"
                             "    on_light: icons/b.svg\n"
                             "    on_dark: icons/b-inverted.svg\n")
            icon = load_links(Path(directory)).icons["backstage"]
            self.assertTrue(icon.paired)
            self.assertEqual(icon.on_dark.path.name, "b-inverted.svg")

    def test_half_a_pair_is_legal_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="icons/g.svg")
            write(directory, "icons:\n  github:\n    on_dark: icons/g.svg\n")
            config = load_links(Path(directory))
            icon = config.icons["github"]
            self.assertTrue(icon.paired)
            self.assertIsNone(icon.on_light)
            self.assertTrue(problems_matching(config, "falls through"))

    def test_none_suppresses_the_mark(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons:\n  aws: none\n  argo: ~\n")
            icons = load_links(Path(directory)).icons
            self.assertTrue(icons["aws"].suppressed)
            self.assertTrue(icons["argo"].suppressed)
            self.assertIsNone(icons["aws"].on_light)

    def test_a_remote_url_is_kept_as_a_url(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons:\n"
                             "  jenkins: https://ci.example.org/favicon.ico\n")
            icon = load_links(Path(directory)).icons["jenkins"]
            self.assertEqual(icon.on_light.url,
                             "https://ci.example.org/favicon.ico")
            self.assertIsNone(icon.on_light.path)

    def test_a_foreign_scheme_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons:\n  odd: ftp://files.example.org/i.svg\n")
            config = load_links(Path(directory))
            self.assertNotIn("odd", config.icons)
            self.assertTrue(problems_matching(config, "is not a http or https URL"))

    def test_a_missing_local_file_is_reported_at_load(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons:\n  ghost: icons/ghost.svg\n")
            config = load_links(Path(directory))
            self.assertNotIn("ghost", config.icons)
            self.assertTrue(problems_matching(config, "does not exist"))

    def test_a_path_outside_the_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons:\n  escape: ../../etc/passwd\n")
            config = load_links(Path(directory))
            self.assertNotIn("escape", config.icons)
            self.assertTrue(problems_matching(config, "points outside"))

    def test_a_later_root_replaces_one_name_whole(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write(d1, "<svg/>", name="icons/a.svg")
            write(d1, "icons:\n  aws: icons/a.svg\n"
                      "  grafana: https://base.example.org/g.svg\n")
            write(d2, "<svg/>", name="icons/aws-light.svg")
            write(d2, "<svg/>", name="icons/aws-dark.svg")
            write(d2, "icons:\n  aws:\n    on_light: icons/aws-light.svg\n"
                      "    on_dark: icons/aws-dark.svg\n")
            icons = load_links(f"{d1}{os.pathsep}{d2}").icons
            self.assertTrue(icons["aws"].paired)
            self.assertEqual(icons["aws"].on_light.path.name, "aws-light.svg")
            # Per name, never wholesale: overriding `aws` leaves `grafana` standing.
            self.assertEqual(icons["grafana"].on_light.url,
                             "https://base.example.org/g.svg")

    def test_an_empty_pair_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons:\n  hollow: {}\n")
            config = load_links(Path(directory))
            self.assertNotIn("hollow", config.icons)
            self.assertTrue(problems_matching(config, "needs on_light or on_dark"))

    def test_an_unnamed_icon_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons:\n  '   ': icons/x.svg\n")
            config = load_links(Path(directory))
            self.assertTrue(problems_matching(config, "an icon needs a name"))

    def test_icons_must_be_a_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons: [grafana]\n")
            config = load_links(Path(directory))
            self.assertEqual(dict(config.icons), {})
            self.assertTrue(problems_matching(config, "must be a mapping"))


class IconResolutionTests(TestCase):
    def test_the_deployment_map_outranks_the_built_in_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="icons/ours.svg")
            write(directory, "icons:\n  grafana: icons/ours.svg\n")
            config = load_links(Path(directory))
            icon = config.icon_for("grafana")
            self.assertIsNotNone(icon)
            self.assertEqual(icon.on_light.path.name, "ours.svg")

    def test_an_undeclared_name_falls_to_the_built_in_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, SIMPLE)
            icon = load_links(Path(directory)).icon_for("grafana")
            self.assertIsNotNone(icon)
            self.assertEqual(icon.on_light.package, BUILTIN_PACKAGE)
            self.assertTrue(icon.paired)

    def test_none_turns_a_built_in_off(self):
        # Without this a built-in could be swapped but never switched off, which is
        # exactly what the redistribution question raises (ADR-0030 §3).
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "icons:\n  aws: none\n")
            icon = load_links(Path(directory)).icon_for("aws")
            self.assertIsNotNone(icon)
            self.assertTrue(icon.suppressed)

    def test_an_empty_name_resolves_to_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(load_links(Path(directory)).icon_for(""))

    def test_a_name_no_rung_defines_is_reported_once(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: T\n    links:\n"
                             "      - {title: A, url: 'https://a.example.org/',"
                             " icon: cyberchef}\n"
                             "      - {title: B, url: 'https://b.example.org/',"
                             " icon: cyberchef}\n"
                             "      - {title: C, url: 'https://c.example.org/',"
                             " icon: grafana}\n")
            config = load_links(Path(directory))
            found = problems_matching(config, "no icon named")
            self.assertEqual(len(found), 1)
            self.assertIn("cyberchef", found[0])
            # …and the entries still load: an undefined name is legal, and falls
            # through to the entry's own favicon.
            self.assertEqual(len(config.groups[0].links), 3)

    def test_a_name_a_later_root_defines_is_not_reported(self):
        # The check runs after every layer is merged, or a base root's entry would
        # be reported for an icon the site root supplies.
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write(d1, "groups:\n  - title: T\n    links:\n"
                      "      - {title: A, url: 'https://a.example.org/',"
                      " icon: phoenix}\n")
            write(d2, "<svg/>", name="icons/phoenix.svg")
            write(d2, "icons:\n  phoenix: icons/phoenix.svg\n")
            config = load_links(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(problems_matching(config, "no icon named"), [])

    def test_a_file_type_we_will_not_serve_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "print()", name="icons/mark.py")
            write(directory, "icons:\n  odd: icons/mark.py\n")
            config = load_links(Path(directory))
            self.assertNotIn("odd", config.icons)
            self.assertTrue(problems_matching(config, "not an icon file type"))


class DiscoveredIconTests(TestCase):
    """`config/links/icons/` is the deployment's own pack: a file there resolves by
    its own name, with no `icons:` entry (ADR-0030)."""

    def test_a_file_resolves_by_its_own_name(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/firewall.svg")
            write(directory, "groups:\n  - title: T\n    links:\n"
                             "      - {title: FW, url: 'https://fw.example.org/',"
                             " icon: firewall}\n", name="links/links.yaml")
            config = load_links(Path(directory))
            self.assertEqual(config.problems, ())
            icon = config.icon_for("firewall")
            self.assertIsNotNone(icon)
            self.assertFalse(icon.paired)          # one file → the chip
            self.assertEqual(icon.on_light.path.name, "firewall.svg")
            self.assertEqual(icon.on_light, icon.on_dark)

    def test_the_built_in_pack_naming_makes_a_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/house-on-light.svg")
            write(directory, "<svg/>", name="links/icons/house-on-dark.svg")
            write(directory, SIMPLE, name="links/links.yaml")
            icon = load_links(Path(directory)).icon_for("house")
            self.assertTrue(icon.paired)
            self.assertEqual(icon.on_light.path.name, "house-on-light.svg")
            self.assertEqual(icon.on_dark.path.name, "house-on-dark.svg")

    def test_a_discovered_file_outranks_a_pack_and_the_built_ins(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/grafana.svg")
            write(directory, SIMPLE, name="links/links.yaml")
            icon = load_links(Path(directory)).icon_for("grafana")
            self.assertEqual(icon.on_light.path.name, "grafana.svg")

    def test_the_map_outranks_a_discovered_file_in_the_same_layer(self):
        # An `icons:` entry is a statement; a file is a convention.
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/firewall.svg")
            write(directory, "<svg/>", name="links/other.svg")
            write(directory, "icons:\n  firewall: other.svg\n",
                  name="links/links.yaml")
            icon = load_links(Path(directory)).icon_for("firewall")
            self.assertEqual(icon.on_light.path.name, "other.svg")

    def test_none_in_the_map_turns_a_discovered_file_off(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/firewall.svg")
            write(directory, "icons:\n  firewall: none\n", name="links/links.yaml")
            self.assertTrue(load_links(Path(directory)).icon_for("firewall").suppressed)

    def test_a_later_root_replaces_the_name_whole(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write(d1, "<svg/>", name="links/icons/mark.svg")
            write(d1, SIMPLE, name="links/links.yaml")
            write(d2, "<svg/>", name="links/icons/mark-on-light.svg")
            write(d2, "<svg/>", name="links/icons/mark-on-dark.svg")
            write(d2, SIMPLE, name="links/links.yaml")
            icon = load_links(f"{d1}{os.pathsep}{d2}").icon_for("mark")
            self.assertTrue(icon.paired)
            # A discovered path is resolved, so compare against a resolved root:
            # on macOS a temporary directory lives under /var, which *is* a symlink
            # to /private/var, and a plain prefix test fails there and nowhere else.
            self.assertTrue(icon.on_light.path.is_relative_to(Path(d2).resolve()))

    def test_a_pair_beats_a_single_of_the_same_name_and_says_so(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/mark.svg")
            write(directory, "<svg/>", name="links/icons/mark-on-light.svg")
            write(directory, "<svg/>", name="links/icons/mark-on-dark.svg")
            write(directory, SIMPLE, name="links/links.yaml")
            config = load_links(Path(directory))
            self.assertTrue(config.icon_for("mark").paired)
            self.assertTrue(problems_matching(config, "mark.svg is unused"))

    def test_two_files_claiming_one_name_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/mark.png")
            write(directory, "<svg/>", name="links/icons/mark.svg")
            write(directory, SIMPLE, name="links/links.yaml")
            config = load_links(Path(directory))
            self.assertTrue(problems_matching(config, "both claim 'mark'"))
            # …and the winner is stable: sorted order, so a rerun picks the same one.
            self.assertEqual(config.icon_for("mark").on_light.path.name, "mark.png")

    def test_half_a_discovered_pair_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/mark-on-dark.svg")
            write(directory, SIMPLE, name="links/links.yaml")
            config = load_links(Path(directory))
            icon = config.icon_for("mark")
            self.assertTrue(icon.paired)
            self.assertIsNone(icon.on_light)
            self.assertTrue(problems_matching(config, "falls through"))

    def test_everything_that_is_not_an_icon_passes_in_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "notes", name="links/icons/README.md")
            write(directory, "", name="links/icons/.DS_Store")
            write(directory, "print()", name="links/icons/build.py")
            write(directory, SIMPLE, name="links/links.yaml")
            config = load_links(Path(directory))
            self.assertEqual(config.problems, ())
            self.assertEqual(dict(config.icons), {})

    def test_the_flat_form_has_no_icons_directory_to_discover(self):
        # An `icons/` beside a flat config/links.yaml is a directory in a
        # configuration root that no aspect claims: nothing reads it, and the startup
        # report names it as unknown (ADR-0070). Which is exactly why an aspect that
        # ships files grows into the directory form.
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="icons/firewall.svg")
            write(directory, SIMPLE)
            self.assertIsNone(load_links(Path(directory)).icon_for("firewall"))

    def test_the_directory_form_needs_no_icons_directory(self):
        # The common case: a deployment whose icons are all built-in or remote takes
        # the directory form for nothing, and nothing here should mind.
        with tempfile.TemporaryDirectory() as directory:
            write(directory, SIMPLE, name="links/links.yaml")
            config = load_links(Path(directory))
            self.assertEqual(config.problems, ())
            self.assertEqual(dict(config.icons), {})

    def test_a_file_that_is_only_a_variant_marker_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/-on-light.svg")
            write(directory, SIMPLE, name="links/links.yaml")
            config = load_links(Path(directory))
            self.assertEqual(dict(config.icons), {})
            self.assertEqual(config.problems, ())

    def test_a_discovered_name_is_not_reported_as_undefined(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/firewall.png")
            write(directory, "groups:\n  - title: T\n    links:\n"
                             "      - {title: FW, url: 'https://fw.example.org/',"
                             " icon: firewall}\n", name="links/links.yaml")
            config = load_links(Path(directory))
            self.assertEqual(problems_matching(config, "no icon named"), [])


class MarkTests(TestCase):
    """How an entry's mark is drawn — which images, and where each is from — which
    is also what the page's own policy allows (ADR-0030 §3–4)."""

    REMOTE = "https://marks.example.org/phoenix.svg"

    def entry(self, url="https://chef.example.org/tool", icon="", icons=None):
        link = Link(title="T", url=url, icon=icon)
        return LinksConfig(icons=icons or {},
                           groups=(Group(title="G", links=(link,)),)), link

    def drawn(self, config, link):
        mark = config.mark_for(link)
        return mark.bare, [(each.variant, each.side, each.url) for each in mark.images]

    def test_a_pack_pair_is_ours_twice_and_needs_no_chip(self):
        config, link = self.entry(icon="grafana")
        self.assertEqual(self.drawn(config, link),
                         (True, [("on-light", "light", ""), ("on-dark", "dark", "")]))

    def test_an_entry_without_a_mark_draws_its_site_favicon_on_the_chip(self):
        config, link = self.entry()
        self.assertEqual(self.drawn(config, link), (False, [
            ("on-light", "", "https://chef.example.org/favicon.ico")]))

    def test_a_name_no_rung_defines_draws_the_favicon_too(self):
        config, link = self.entry(icon="cyberchef")
        self.assertEqual(self.drawn(config, link), (False, [
            ("on-light", "", "https://chef.example.org/favicon.ico")]))

    def test_a_mark_turned_off_falls_through_to_the_favicon(self):
        config, link = self.entry(icon="aws",
                                  icons={"aws": Icon(name="aws", suppressed=True)})
        self.assertEqual(self.drawn(config, link), (False, [
            ("on-light", "", "https://chef.example.org/favicon.ico")]))

    def test_a_remote_mark_keeps_its_own_url_in_one_image(self):
        remote = Icon(name="phoenix", on_light=IconFile(url=self.REMOTE),
                      on_dark=IconFile(url=self.REMOTE))
        config, link = self.entry(icon="phoenix", icons={"phoenix": remote})
        self.assertEqual(self.drawn(config, link),
                         (False, [("on-light", "", self.REMOTE)]))

    def test_half_a_pair_takes_the_favicon_for_the_other_background(self):
        half = Icon(name="half", on_light=IconFile(url=self.REMOTE), paired=True)
        config, link = self.entry(icon="half", icons={"half": half})
        self.assertEqual(self.drawn(config, link), (False, [
            ("on-light", "light", self.REMOTE),
            ("on-dark", "dark", "https://chef.example.org/favicon.ico")]))

    def test_the_page_names_each_host_it_sends_a_browser_to_once_in_order(self):
        remote = Icon(name="phoenix", on_light=IconFile(url=self.REMOTE),
                      on_dark=IconFile(url=self.REMOTE))
        config = LinksConfig(icons={"phoenix": remote}, groups=(
            Group(title="G", links=(
                Link(title="Chef", url="https://chef.example.org/tool"),
                Link(title="Grafana", url="https://grafana.example.org/",
                     icon="grafana"),
                Link(title="Phoenix", url="https://phoenix.example.org/",
                     icon="phoenix"))),
            Group(title="H", links=(
                Link(title="Chef again", url="https://chef.example.org/other"),)),
        ))
        self.assertEqual(config.external_icon_urls(),
                         ("https://chef.example.org/favicon.ico", self.REMOTE))

    def test_a_page_of_our_own_marks_sends_a_browser_nowhere(self):
        config, _ = self.entry(icon="grafana")
        self.assertEqual(config.external_icon_urls(), ())

    def test_the_favicon_is_the_root_of_the_site_the_link_is_on(self):
        self.assertEqual(favicon_url("https://a.example.org:8443/deep/path?q=1"),
                         "https://a.example.org:8443/favicon.ico")
        self.assertEqual(favicon_url("not a url"), "")


class PolicySourceTests(TestCase):
    """The hosts ``/links`` allows for itself are the ones the file names
    (ADR-0030, ADR-0048)."""

    def test_the_icon_hosts_come_from_the_file_and_answer_to_it(self):
        text = """
icons:
  phoenix: https://marks.example.org/phoenix.svg
groups:
  - title: T
    links:
      - title: Chef
        url: https://chef.example.org/tool
      - title: Phoenix
        url: https://phoenix.example.org/
        icon: phoenix
      - title: Grafana
        url: https://grafana.example.org/
        icon: grafana
"""
        with tempfile.TemporaryDirectory() as directory:
            write(directory, text)
            config = load_links(Path(directory))
            sources = links_policy_sources(config)
        # The favicon of the entry with no mark and the host of the remote mark —
        # not every host the page links to: a link with a mark of its own loads
        # nothing from its site.
        self.assertEqual([source.value for source in sources],
                         ["https://chef.example.org", "https://marks.example.org"])
        self.assertEqual({source.by for source in sources},
                         {str(path) for path in config.sources})
        self.assertEqual(len(config.sources), 1)

    def test_a_file_whose_marks_are_all_ours_adds_nothing(self):
        text = ("groups:\n  - title: T\n    links:\n      - title: Grafana\n"
                "        url: https://grafana.example.org/\n        icon: grafana\n")
        with tempfile.TemporaryDirectory() as directory:
            write(directory, text)
            self.assertEqual(links_policy_sources(load_links(Path(directory))), ())


class RetiredCheckKeyTests(TestCase):
    """The page probes nothing (ADR-0030), so a `check:` block, or an entry's
    `check:`, is a key the file does not have — reported as any other is, and the
    entry it sits on still shown."""

    def test_a_check_block_is_an_unknown_key(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "check:\n  icons: true\n  interval: 6h\n")
            config = load_links(Path(directory))
            self.assertTrue(problems_matching(config, "unknown key(s) check"))

    def test_an_entry_that_asks_to_be_checked_is_still_shown(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "groups:\n  - title: T\n    links:\n      - title: A\n"
                             "        url: https://a.example.org/\n"
                             "        check: true\n")
            config = load_links(Path(directory))
            self.assertEqual([link.title for link in config.groups[0].links], ["A"])
            self.assertTrue(problems_matching(config, "unknown key(s) check"))


class DirectoryFormTests(TestCase):
    def test_the_document_lives_inside_the_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, SIMPLE, name="links/links.yaml")
            write(directory, "<svg/>", name="links/icons/phoenix.svg")
            config = load_links(Path(directory))
            self.assertEqual(config.groups[0].title, "Toolbox")
            self.assertEqual(config.sources[0].parent.name, "links")

    def test_relative_icons_resolve_against_the_document(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/phoenix.svg")
            write(directory, "icons:\n  phoenix: icons/phoenix.svg\n",
                  name="links/links.yaml")
            icon = load_links(Path(directory)).icons["phoenix"]
            self.assertEqual(icon.on_light.path,
                             (Path(directory) / "links/icons/phoenix.svg").resolve())

    def test_a_directory_without_a_document_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/phoenix.svg")
            config = load_links(Path(directory))
            self.assertEqual(config.groups, ())
            self.assertTrue(problems_matching(config, "no links.yaml"))

    def test_both_suffixes_in_the_directory_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, SIMPLE, name="links/links.yaml")
            write(directory, SIMPLE, name="links/links.yml")
            config = load_links(Path(directory))
            self.assertEqual(config.groups, ())
            self.assertTrue(problems_matching(config, "keep one"))

    def test_the_aspect_is_registered_in_both_forms(self):
        self.assertTrue(ASPECTS["links"].as_file)
        self.assertTrue(ASPECTS["links"].as_directory)
        with tempfile.TemporaryDirectory() as directory:
            write(directory, SIMPLE)
            self.assertEqual(aspect_in(Path(directory), "links"),
                             Path(directory) / "links.yaml")


class CachingTests(TestCase):
    def setUp(self):
        forget_cached_links()
        self.addCleanup(forget_cached_links)

    def test_an_unchanged_file_is_not_parsed_again(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, SIMPLE)
            first = current_links(Path(directory))
            self.assertIs(current_links(Path(directory)), first)

    def test_an_edit_is_picked_up_without_a_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, SIMPLE)
            self.assertEqual(len(current_links(Path(directory)).groups), 1)
            write(directory, SIMPLE + "  - title: Second\n")
            self.assertEqual([group.title
                              for group in current_links(Path(directory)).groups],
                             ["Toolbox", "Second"])

    def test_a_file_appearing_is_picked_up(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(current_links(Path(directory)).is_empty())
            write(directory, SIMPLE)
            self.assertFalse(current_links(Path(directory)).is_empty())

    def test_a_directory_without_a_document_stats_without_crashing(self):
        # The stamp walks the same layers as the load, and must survive everything
        # the load merely complains about.
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "<svg/>", name="links/icons/phoenix.svg")
            self.assertTrue(current_links(Path(directory)).is_empty())
            write(directory, SIMPLE, name="links/links.yaml")
            self.assertFalse(current_links(Path(directory)).is_empty())

    def test_a_second_path_list_does_not_reuse_the_first_parse(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write(d1, SIMPLE)
            self.assertFalse(current_links(Path(d1)).is_empty())
            self.assertTrue(current_links(Path(d2)).is_empty())


if __name__ == "__main__":
    unittest.main()
