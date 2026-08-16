"""A loaded-from path is drawn against a root the reader has
(`little_sister.paths`)."""
import sysconfig
from pathlib import Path
from unittest import TestCase

from little_sister.paths import shown_path

#: A deployment as it actually sits on disk: a checkout with its virtualenv inside
#: it, which is what makes *both* roots match an installed package.
PROJECT = "/Users/someone/Projects/deployment"
SITE = f"{PROJECT}/.venv/lib/python3.14/site-packages"


def shown(path):
    return shown_path(path, environment=[SITE], project=PROJECT)


class ShownPathTests(TestCase):
    def test_an_installed_package_is_named_by_its_site_packages(self):
        # the ordinary row, and the string this slice exists to stop printing
        self.assertEqual(
            shown(f"{SITE}/little_sister_github/github.py"),
            "site-packages/little_sister_github/github.py")

    def test_a_checkout_beside_the_config_is_named_by_the_project(self):
        # the case that matters: a source copy earlier on sys.path shadowing an
        # installed distribution of the same name — still legible as such
        self.assertEqual(shown(f"{PROJECT}/little_sister_stress/checks.py"),
                         "./little_sister_stress/checks.py")

    def test_the_venv_inside_the_project_is_not_read_as_the_project(self):
        # both roots contain the file; the longer one is the one that says
        # something the reader did not already know
        self.assertNotIn(".venv", shown(f"{SITE}/little_sister_wiz/wiz.py"))

    def test_a_path_under_neither_root_stays_long(self):
        # not a gap — a module loaded from somewhere the reader has no root for is
        # exactly what the long string is there to announce
        strange = "/opt/vendor/lib/python3.14/things/little_sister_x/x.py"
        self.assertEqual(shown(strange), strange)

    def test_no_root_prints_the_home_directory_it_sits_in(self):
        for path in (f"{SITE}/little_sister_github/github.py",
                     f"{PROJECT}/little_sister_stress/checks.py"):
            with self.subTest(path=path):
                self.assertNotIn("/Users/someone", shown(path))

    def test_a_module_with_no_file_stays_empty(self):
        # `getattr(module, "__file__", "")` is how an origin records one, and the
        # templates test it for truth before printing anything
        self.assertEqual(shown(""), "")

    def test_this_process_answers_when_nobody_says_otherwise(self):
        # the arguments exist for the tests above; the default is the running
        # interpreter's own site-packages, and this asserts they are the same rule
        purelib = sysconfig.get_paths()["purelib"]
        self.assertEqual(shown_path(f"{purelib}/little_sister_github/github.py"),
                         f"{Path(purelib).name}/little_sister_github/github.py")
        self.assertEqual(shown_path(str(Path.cwd() / "wsgi.py")), "./wsgi.py")

    def test_a_user_install_is_an_environment_too(self):
        # `pip install --user` lands under the operator's home directory, so
        # leaving that scheme out would print exactly what this rule is here to
        # keep off the page
        user = sysconfig.get_paths(
            sysconfig.get_preferred_scheme("user"))["purelib"]
        self.assertEqual(shown_path(f"{user}/little_sister_jira/jira.py"),
                         f"{Path(user).name}/little_sister_jira/jira.py")
