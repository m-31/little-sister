import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase, mock

from little_sister import process
from little_sister.checks import CheckError, Measurement
from little_sister.checks.ssh import HostMetricsCheck, _parse_disk_path
from little_sister.checks.ssh.metrics import volume_name
from little_sister.engine import Engine
from little_sister.limits import RECORD_LIMIT
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.running import (
    SSH_RUN,
    finished,
    record_of,
    remote_args,
    remote_parts,
    run_check,
)

SSH_SAMPLE = """\
os=Linux
hostname=alpha
ncpu=4
uptime_seconds=90061
disk_path=/
disk_total_kb=1000000
disk_used_kb=850000
disk_avail_kb=150000
disk_pct=85
mem_total_kb=16000000
mem_used_kb=8000000
mem_pct=50
cpu_pct=7
load1=0.40
load5=0.30
load15=0.20
"""

CONFIG_CHECKS_DIR = Path(__file__).resolve().parent.parent / "config" / "checks"


class HostMetricsCheckTests(TestCase):
    def _check(self, directory, **extra):
        script = Path(directory) / "metrics.sh"
        script.write_text("echo hi\n")
        config = {"type": "host-metrics", "path": "/ssh", "host": "host.example",
                  "script": "metrics.sh"}
        config.update(extra)
        return HostMetricsCheck.from_config(config, Path(directory))

    def _run(self, directory, stdout, *, returncode=0, stderr="", **extra):
        check = self._check(directory, **extra)
        completed = finished(stdout, returncode, stderr)
        with mock.patch(SSH_RUN,
                        return_value=completed) as run:
            return run_check(check), run

    def _kids(self, result):
        return {child.name: child for child in result.children}

    def _record(self, directory, stdout, *, returncode=0, stderr="", **extra):
        check = self._check(directory, **extra)
        completed = finished(stdout, returncode, stderr)
        with mock.patch(SSH_RUN,
                        return_value=completed):
            return check, record_of(check)

    # --- the reading (ADR-0086) ---------------------------------------------

    def test_the_reading_holds_numbers_and_not_the_script_s_strings(self):
        """A curve is drawn from a record, and a series of `"85"` is a series of
        text. The key already names the unit, so the value is a number — and an
        integral one reads as a count rather than as `4.0`."""
        with tempfile.TemporaryDirectory() as directory:
            _, record = self._record(directory, SSH_SAMPLE)
        self.assertEqual(record["disk_pct"], 85)
        self.assertEqual(record["mem_pct"], 50)
        self.assertEqual(record["load1"], 0.4)
        self.assertEqual(record["ncpu"], 4)
        for key in ("disk_pct", "mem_pct", "cpu_pct", "load1", "ncpu"):
            self.assertIsInstance(record[key], (int, float), key)
            self.assertNotIsInstance(record[key], str, key)

    def test_a_key_the_script_did_not_give_stands_as_null(self):
        """One shape per check, so a curve draws a real gap from a null instead of
        inferring one from a key that is not there (ADR-0085 decision 3). The
        grading then has one case to handle, not two."""
        partial = "os=Linux\nhostname=alpha\ndisk_pct=85\nload1=notanumber\n"
        with tempfile.TemporaryDirectory() as directory:
            check, record = self._record(directory, partial)
        self.assertIn("mem_pct", record)
        self.assertIsNone(record["mem_pct"])
        self.assertIn("load1", record)
        self.assertIsNone(record["load1"], "unparseable is null, not the string")
        kids = self._kids(check.grade((Measurement(record=record),),
                                      datetime.now(UTC)))
        self.assertEqual(kids["memory"].code, StatusCode.WARN)
        self.assertEqual(kids["memory"].reason, ["unavailable"])

    def test_the_grading_works_from_a_record_it_never_measured(self):
        """The whole point of the split, tested the way the authoring guide now
        tells an author to test it: hand the grading a record written by hand —
        which is exactly what a series will hand it a year from now — and it
        answers without touching ssh at all.

        `subprocess.run` is replaced by something that *refuses*, so the test
        cannot pass by quietly reaching for the world.
        """
        with tempfile.TemporaryDirectory() as directory:
            check = self._check(directory, thresholds={"disk": {"warn": 80,
                                                                "error": 90}})
        typed = Measurement(record={
            "exit_code": 0, "disk_pct": 93, "disk_avail_kb": 70000,
            "disk_total_kb": 1000000, "disk_path": "/", "mem_pct": 50,
            "cpu_pct": 7, "load1": 0.4, "ncpu": 4, "os": "Linux",
            "hostname": "alpha", "uptime_seconds": 90061})
        with mock.patch(SSH_RUN,
                        side_effect=AssertionError("the grading read the world")):
            kids = self._kids(check.grade((typed,), datetime.now(UTC)))
        self.assertEqual(kids["disk"].code, StatusCode.ERROR)
        self.assertIn("93% used", kids["disk"].reason[0])
        self.assertEqual(kids["ssh"].reason[0],
                         "alpha reachable — Linux, 4 CPUs, up 1d 1h")

    def test_the_object_is_the_host_and_not_the_node_path(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self._check(directory).subject, "host.example")

    def test_the_declared_record_is_known_per_volume_and_unknown_for_all(self):
        """ADR-0075's lower-bound reading, applied honestly: a check that cannot
        know its estate declares nothing rather than guessing, and `disk_path:
        all` puts the volume count in the host's hands."""
        with tempfile.TemporaryDirectory() as directory:
            one = self._check(directory)
            listed = self._check(directory, disk_path=["/", "/data", "/backup"])
            every = self._check(directory, disk_path="all")
        self.assertIsNone(every.expected_record())
        assert one.expected_record() is not None
        assert listed.expected_record() is not None
        self.assertGreater(listed.expected_record(), one.expected_record())
        self.assertLessEqual(listed.expected_record(), RECORD_LIMIT)

    def test_host_node_has_ssh_leaf_and_metric_siblings(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, SSH_SAMPLE)
        # the check populates the host node — a neutral container
        self.assertEqual(result.code, StatusCode.UNDEFINED)
        kids = self._kids(result)
        self.assertEqual(set(kids), {"ssh", "disk", "memory", "cpu", "load"})
        # ssh is a peer transport leaf carrying the reachability summary
        self.assertEqual(kids["ssh"].code, StatusCode.OK)
        self.assertIn("alpha reachable", kids["ssh"].reason[0])
        self.assertIn("4 CPUs", kids["ssh"].reason[0])
        self.assertIn("up 1d 1h", kids["ssh"].reason[0])
        # disk 85% lands in the default warn band (>=80, <90)
        self.assertEqual(kids["disk"].code, StatusCode.WARN)
        self.assertIn("85% used", kids["disk"].reason[0])
        self.assertIn("free of", kids["disk"].reason[0])
        # OK aspects still carry their number
        self.assertEqual(kids["memory"].code, StatusCode.OK)
        self.assertIn("50% used", kids["memory"].reason[0])
        self.assertEqual(kids["cpu"].reason, ["7% busy"])
        self.assertIn("0.10 per core", kids["load"].reason[0])

    def test_metric_children_and_ssh_leaf_carry_config(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, SSH_SAMPLE)
        kids = self._kids(result)
        # each metric leaf carries its own grading thresholds (ADR-0013)
        self.assertIn("80%", kids["disk"].config)
        self.assertIn("90%", kids["disk"].config)
        self.assertIn("85%", kids["memory"].config)
        self.assertIn("0.8", kids["load"].config)        # per-core, no % unit
        # the ssh leaf carries the connection (host / profile), not thresholds
        self.assertIn("host.example", kids["ssh"].config)
        self.assertIn("linux", kids["ssh"].config)
        # the shared host container itself stays bare
        self.assertEqual(result.config, "")

    # --- the labels (ADR-0025) ---
    #
    # They are read off the **tree**, not off the result, because under ADR-0025
    # this check declares them and the library resolves them:
    # the child `CheckResult` carries nothing for a name the type knows, and a
    # test asserting on the result would now be testing the wrong layer — and
    # would have gone on passing, vacuously, when the labels stopped arriving.
    # What a deployment sees is the node, so that is what these pin.

    def _nodes(self, directory, stdout, **extra):
        """Every node this check writes, by path, after one engine tick."""
        check = self._check(directory, **extra)
        completed = finished(stdout, 0, "")
        tree = StatusTree()
        with mock.patch(SSH_RUN,
                        return_value=completed):
            Engine([check], tree).run_once()
        nodes = {}

        def walk(node, path):
            nodes[path] = node
            for child in node.children:
                walk(child, f"{path}/{child.name}")

        walk(tree.snapshot("/ssh"), "/ssh")
        return nodes

    def test_metric_nodes_carry_the_declared_about(self):
        # Each aspect leaf gets the type-inherent `about` this check declares
        # (ADR-0025); the copy lives in the ABOUT map, so every deployment's hover
        # cards explain these leaves out of the box. A deployment's nodes.yaml
        # still overrides per field.
        from little_sister.checks.ssh.host_metrics import ABOUT
        with tempfile.TemporaryDirectory() as directory:
            nodes = self._nodes(directory, SSH_SAMPLE)
        for aspect in ("ssh", "disk", "memory", "cpu", "load"):
            self.assertEqual(nodes[f"/ssh/{aspect}"].about, ABOUT[aspect])
        # the shared host container carries none — its labels stay nodes.yaml's
        self.assertEqual(nodes["/ssh"].about, "")

    def test_the_declaration_is_all_this_check_does_with_a_label(self):
        # The migration's claim, stated where it can fail: the aspect children
        # hand over no label at all any more — the map on the check is what the
        # engine writes. (The per-volume children below are the one exception,
        # and they are dynamic.)
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, SSH_SAMPLE)
        for child in result.children:
            with self.subTest(aspect=child.name):
                self.assertEqual((child.about, child.title), ("", ""))

    def test_unavailable_aspect_still_carries_about(self):
        # a missing aspect is a WARN "unavailable" leaf, but its hover still
        # explains what the leaf is (ADR-0025).
        from little_sister.checks.ssh.host_metrics import ABOUT
        stdout = "disk_pct=10\ncpu_pct=5\nload1=0.1\nncpu=2\n"   # memory absent
        with tempfile.TemporaryDirectory() as directory:
            nodes = self._nodes(directory, stdout)
        memory = nodes["/ssh/memory"]
        self.assertEqual(list(memory.reason), ["unavailable"])
        self.assertEqual(memory.about, ABOUT["memory"])

    def test_disk_volumes_carry_the_disk_about(self):
        # the `disk_path: all` branch and each per-filesystem volume carry the
        # disk about, so every volume hover explains itself too. The branch is
        # named `disk` and is labeled by the library; a volume is named by the
        # host, so its label rides its result — the dynamic-child channel.
        from little_sister.checks.ssh.host_metrics import ABOUT
        stdout = (
            "disk_count=2\n"
            "disk1_path=/\ndisk1_total_kb=1000000\ndisk1_used_kb=520000\n"
            "disk1_avail_kb=480000\ndisk1_pct=52\n"
            "disk2_path=/mnt/ext\ndisk2_total_kb=379888\ndisk2_used_kb=375916\n"
            "disk2_avail_kb=3972\ndisk2_pct=99\n"
            "mem_pct=30\ncpu_pct=5\nload1=0.5\nncpu=2\n")
        with tempfile.TemporaryDirectory() as directory:
            nodes = self._nodes(directory, stdout)
        self.assertEqual(nodes["/ssh/disk"].about, ABOUT["disk"])
        self.assertEqual(nodes["/ssh/disk/root"].about, ABOUT["disk"])
        self.assertEqual(nodes["/ssh/disk/ext"].about, ABOUT["disk"])

    def test_subnodes_config_overrides_the_declared_about(self):
        # a deployment overrides a declared aspect about (and sets a title) in the
        # check's own config — per aspect, per field (ADR-0025).
        from little_sister.checks.ssh.host_metrics import ABOUT
        with tempfile.TemporaryDirectory() as directory:
            nodes = self._nodes(
                directory, SSH_SAMPLE,
                subnodes={"disk": {"about": "Root volume on the NVMe.",
                                   "title": "Disk (NVMe)"}})
        self.assertEqual(nodes["/ssh/disk"].about, "Root volume on the NVMe.")
        self.assertEqual(nodes["/ssh/disk"].title, "Disk (NVMe)")
        self.assertEqual(nodes["/ssh/memory"].about, ABOUT["memory"])  # default
        self.assertEqual(nodes["/ssh/memory"].title, "")   # no title declared

    def test_subnodes_title_only_keeps_default_about(self):
        # a config entry that sets only a title leaves the declared about in place
        # (an empty field falls back to the default, per field).
        from little_sister.checks.ssh.host_metrics import ABOUT
        with tempfile.TemporaryDirectory() as directory:
            nodes = self._nodes(
                directory, SSH_SAMPLE, subnodes={"cpu": {"title": "Processor"}})
        self.assertEqual(nodes["/ssh/cpu"].title, "Processor")
        self.assertEqual(nodes["/ssh/cpu"].about, ABOUT["cpu"])

    def test_subnodes_config_may_extend_the_declared_about(self):
        # `{default}` is the extension form, and it works for an installed type
        # from the deployment's file alone (ADR-0025).
        from little_sister.checks.ssh.host_metrics import ABOUT
        with tempfile.TemporaryDirectory() as directory:
            nodes = self._nodes(
                directory, SSH_SAMPLE,
                subnodes={"memory": {"about": "{default}\n\nAlso ping #oncall."}})
        self.assertEqual(nodes["/ssh/memory"].about,
                         ABOUT["memory"] + "\n\nAlso ping #oncall.")

    def test_subnodes_override_reaches_disk_branch_and_volumes(self):
        # the disk override applies to the `disk_path: all` branch and each volume
        # (they share the disk aspect's label — the volumes because this check
        # hands them the *resolved* text, the override included).
        stdout = (
            "disk_count=1\n"
            "disk1_path=/\ndisk1_total_kb=1000000\ndisk1_used_kb=520000\n"
            "disk1_avail_kb=480000\ndisk1_pct=52\n"
            "mem_pct=30\ncpu_pct=5\nload1=0.5\nncpu=2\n")
        with tempfile.TemporaryDirectory() as directory:
            nodes = self._nodes(
                directory, stdout,
                subnodes={"disk": {"about": "Volumes on this NAS."}})
        self.assertEqual(nodes["/ssh/disk"].about, "Volumes on this NAS.")
        self.assertEqual(nodes["/ssh/disk/root"].about, "Volumes on this NAS.")

    def test_descriptions_override_leaf_descriptions(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(
                directory, SSH_SAMPLE,
                descriptions={"disk": "root volume", "ssh": "the link"})
        kids = self._kids(result)
        self.assertEqual(kids["disk"].description, "root volume")
        self.assertEqual(kids["ssh"].description, "the link")
        self.assertIn("Memory", kids["memory"].description)   # default kept

    def test_thresholds_grade_each_aspect(self):
        stdout = ("disk_pct=95\nmem_pct=90\ncpu_pct=99\n"
                  "load1=10\nncpu=4\n")
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, stdout)
        aspects = {child.name: child.code for child in result.children}
        self.assertEqual(aspects["disk"], StatusCode.ERROR)    # >=90
        self.assertEqual(aspects["memory"], StatusCode.WARN)   # 85<=90<95
        self.assertEqual(aspects["cpu"], StatusCode.ERROR)     # >=95
        self.assertEqual(aspects["load"], StatusCode.ERROR)    # 10/4=2.5/core

    def test_threshold_override_from_config(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(
                directory, "disk_pct=15\n",
                thresholds={"disk": {"warn": 10, "error": 20}})
        disk = next(c for c in result.children if c.name == "disk")
        self.assertEqual(disk.code, StatusCode.WARN)

    def test_disk_all_builds_a_branch_per_volume(self):
        stdout = (
            "disk_count=3\n"
            "disk1_path=/\ndisk1_total_kb=1000000\ndisk1_used_kb=520000\n"
            "disk1_avail_kb=480000\ndisk1_pct=52\n"
            "disk2_path=/share/MD0_DATA\ndisk2_total_kb=971319676\n"
            "disk2_used_kb=887712964\ndisk2_avail_kb=83082424\ndisk2_pct=91\n"
            "disk3_path=/mnt/ext\ndisk3_total_kb=379888\ndisk3_used_kb=375916\n"
            "disk3_avail_kb=3972\ndisk3_pct=99\n"
            "mem_pct=30\ncpu_pct=5\nload1=0.5\nncpu=2\n")
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, stdout)
        disk = self._kids(result)["disk"]
        # disk is now a branch (neutral container) with one child per volume
        self.assertEqual(disk.code, StatusCode.UNDEFINED)
        vols = {c.name: c for c in disk.children}
        self.assertEqual(set(vols), {"root", "MD0_DATA", "ext"})
        self.assertEqual(vols["root"].code, StatusCode.OK)        # 52%
        self.assertEqual(vols["MD0_DATA"].code, StatusCode.ERROR)  # 91% (>=90)
        self.assertEqual(vols["ext"].code, StatusCode.ERROR)       # 99%
        self.assertIn("91% used", vols["MD0_DATA"].reason[0])
        self.assertIn("/share/MD0_DATA", vols["MD0_DATA"].reason[0])
        # the other aspects are unaffected
        self.assertEqual(self._kids(result)["cpu"].reason, ["5% busy"])

    def test_disk_path_list_is_joined_and_passed_to_script(self):
        with tempfile.TemporaryDirectory() as directory:
            _, run = self._run(directory, SSH_SAMPLE,
                               disk_path=["/share/A", "/share/B"])
        self.assertEqual(remote_args(run), ["/share/A\n/share/B"])

    def test_parse_disk_path(self):
        self.assertEqual(_parse_disk_path("/x"), "/x")
        self.assertEqual(_parse_disk_path("all"), "all")
        self.assertIsNone(_parse_disk_path(None))
        self.assertEqual(_parse_disk_path(["/x"]), "/x")          # 1-item == single
        self.assertEqual(_parse_disk_path(["/x", "/y"]), "/x\n/y")

    def test_volume_name_sanitises_and_dedupes(self):
        used: set[str] = set()
        self.assertEqual(volume_name("/", used), "root")
        self.assertEqual(volume_name("/share/MD0_DATA", used), "MD0_DATA")
        self.assertEqual(volume_name("/a/data", used), "data")
        self.assertEqual(volume_name("/b/data", used), "data_2")        # de-duped
        self.assertEqual(volume_name("/Volumes/My Disk", used), "My_Disk")

    def test_missing_metric_is_unavailable_not_fatal(self):
        # memory absent, but the rest present → memory WARN, ssh still OK
        stdout = "disk_pct=10\ncpu_pct=5\nload1=0.1\nncpu=2\n"
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, stdout)
        kids = self._kids(result)
        self.assertEqual(kids["ssh"].code, StatusCode.OK)
        self.assertEqual(kids["memory"].code, StatusCode.WARN)
        self.assertEqual(kids["memory"].reason, ["unavailable"])

    def test_ssh_failure_marks_ssh_leaf_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(
                directory, "", returncode=255,
                stderr="ssh: connect to host host.example port 22: "
                       "Connection refused")
        # only the failed transport leaf this run — no metrics
        self.assertEqual(result.code, StatusCode.UNDEFINED)
        kids = self._kids(result)
        self.assertEqual(set(kids), {"ssh"})
        self.assertEqual(kids["ssh"].code, StatusCode.ERROR)
        self.assertIn("Connection refused", kids["ssh"].reason[0])
        self.assertIn("exit 255", kids["ssh"].reason[0])

    def test_zero_exit_without_metrics_marks_ssh_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, "some unexpected banner\n")
        ssh = self._kids(result)["ssh"]
        self.assertEqual(ssh.code, StatusCode.ERROR)
        self.assertIn("no metrics", ssh.reason[0])

    def test_ssh_warning_banner_stripped_from_error(self):
        # on a *failed* run the post-quantum (etc.) advisory must not crowd out
        # the real error in the ssh leaf's reason
        stderr = (
            '** WARNING: connection is not using a post-quantum key exchange'
            ' algorithm. **\n'
            '** This session may be vulnerable to "store now, decrypt later"'
            ' attacks. **\n'
            'bash: scripts/host-metrics.sh: No such file or directory\n')
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, "", returncode=127, stderr=stderr)
        ssh = self._kids(result)["ssh"]
        self.assertEqual(ssh.code, StatusCode.ERROR)
        self.assertIn("No such file or directory", ssh.reason[0])
        self.assertNotIn("post-quantum", ssh.reason[0])
        self.assertNotIn("**", ssh.reason[0])

    def test_ssh_warning_surfaces_as_warn_on_ssh_leaf(self):
        # on a *successful* run the advisory makes the ssh transport leaf WARN,
        # while the metrics keep their own status
        stderr = (
            '** WARNING: connection is not using a post-quantum key exchange'
            ' algorithm. **\n'
            '** See https://openssh.com/pq.html **\n')
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, SSH_SAMPLE, stderr=stderr)
        kids = self._kids(result)
        self.assertEqual(kids["ssh"].code, StatusCode.WARN)
        joined = " ".join(kids["ssh"].reason)
        self.assertIn("post-quantum", joined)
        self.assertNotIn("**", joined)
        self.assertEqual(kids["cpu"].code, StatusCode.OK)

    def test_timeout_marks_ssh_error(self):
        with tempfile.TemporaryDirectory() as directory:
            check = self._check(directory, timeout="2s")
            with mock.patch(
                    SSH_RUN,
                    return_value=finished(returncode=-15, ended=process.Ended.BOUND)):
                result = run_check(check)
        ssh = self._kids(result)["ssh"]
        self.assertEqual(ssh.code, StatusCode.ERROR)
        self.assertIn("timed out", ssh.reason[0])

    def test_builds_ssh_command_and_pipes_script(self):
        with tempfile.TemporaryDirectory() as directory:
            _, run = self._run(
                directory, SSH_SAMPLE, user="mon", port=2222, sudo=True,
                identity_file="/keys/id", options=["-o", "X=Y"],
                disk_path="/data")
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertTrue(any(a.startswith("ConnectTimeout=") for a in argv))
        self.assertEqual(argv[argv.index("-i") + 1], "/keys/id")
        self.assertEqual(argv[argv.index("-p") + 1], "2222")
        self.assertIn("X=Y", argv)
        self.assertIn("mon@host.example", argv)
        self.assertEqual(remote_parts(run), ("sudo -n bash -s", "echo hi\n"))
        self.assertEqual(remote_args(run), ["/data"])

    def test_excludes_ssh_rsa_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            _, run = self._run(directory, SSH_SAMPLE)
        self.assertIn("PubkeyAcceptedAlgorithms=-ssh-rsa", run.call_args.args[0])

    def test_options_override_the_ssh_rsa_default(self):
        # a host that still needs ssh-rsa can re-enable it; the user option comes
        # first, so ssh uses it instead of our default
        with tempfile.TemporaryDirectory() as directory:
            _, run = self._run(
                directory, SSH_SAMPLE,
                options=["-o", "PubkeyAcceptedAlgorithms=+ssh-rsa"])
        argv = run.call_args.args[0]
        self.assertLess(argv.index("PubkeyAcceptedAlgorithms=+ssh-rsa"),
                        argv.index("PubkeyAcceptedAlgorithms=-ssh-rsa"))

    def test_debug_surfaces_raw_stderr_and_script_lines(self):
        stdout = SSH_SAMPLE + "debug_df_raw=map auto_home 0 0 0 100% /home\n"
        stderr = ("** WARNING: connection is not using a post-quantum key"
                  " exchange algorithm. **\n")
        with tempfile.TemporaryDirectory() as directory:
            result, run = self._run(directory, stdout, stderr=stderr, debug=True)
        ssh = self._kids(result)["ssh"]
        joined = " ".join(ssh.reason)
        self.assertIn("debug: exit=0", joined)
        self.assertIn("post-quantum", joined)       # raw stderr surfaced verbatim
        self.assertIn("debug_df_raw", joined)        # script debug line surfaced
        self.assertIn("auto_home", joined)
        # the script was asked for debug output
        self.assertEqual(remote_args(run)[-1], "debug")

    def test_no_debug_lines_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            result, run = self._run(directory, SSH_SAMPLE, stderr="noise\n")
        self.assertNotIn("debug", " ".join(self._kids(result)["ssh"].reason))
        self.assertNotIn("debug", remote_args(run))

    # --- profile: script + interpreter selection ---

    def test_default_profile_is_linux(self):
        check = HostMetricsCheck.from_config(
            {"type": "host-metrics", "path": "/x", "host": "h"}, CONFIG_CHECKS_DIR)
        self.assertEqual((check.profile, check.interpreter), ("linux", "bash"))
        self.assertTrue(check.script_path.endswith("host-metrics-linux.sh"))

    def test_macos_profile_selects_bash_and_script(self):
        check = HostMetricsCheck.from_config(
            {"type": "host-metrics", "path": "/x", "host": "h", "profile": "macos"},
            CONFIG_CHECKS_DIR)
        self.assertEqual(check.interpreter, "bash")
        self.assertTrue(check.script_path.endswith("host-metrics-macos.sh"))

    def test_busybox_profile_selects_sh_and_script(self):
        check = HostMetricsCheck.from_config(
            {"type": "host-metrics", "path": "/x", "host": "h", "profile": "busybox"},
            CONFIG_CHECKS_DIR)
        self.assertEqual(check.interpreter, "sh")
        self.assertTrue(check.script_path.endswith("host-metrics-busybox.sh"))

    def test_busybox_profile_pipes_to_sh(self):
        with tempfile.TemporaryDirectory() as directory:
            _, run = self._run(directory, SSH_SAMPLE, profile="busybox",
                               disk_path="/")
        self.assertEqual(remote_parts(run)[0], "sh -s")
        self.assertEqual(remote_args(run), ["/"])

    def test_unknown_profile_raises(self):
        with self.assertRaises(CheckError):
            HostMetricsCheck.from_config(
                {"type": "host-metrics", "path": "/x", "host": "h",
                 "profile": "freebsd"},
                CONFIG_CHECKS_DIR)

    def test_profile_mismatch_is_warn_without_metrics(self):
        # the remote guard rejected the profile (wrong OS family): a config error,
        # surfaced as a WARN ssh leaf with no metric siblings, not a hard ERROR.
        stdout = ("os=Linux\nhostname=h\nprofile_error=macos profile expects a "
                  "Darwin host but uname reports 'Linux'\n")
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, stdout, profile="macos")
        kids = self._kids(result)
        self.assertEqual(set(kids), {"ssh"})
        self.assertEqual(kids["ssh"].code, StatusCode.WARN)
        self.assertIn("profile mismatch", kids["ssh"].reason[0])
        self.assertIn("Darwin", kids["ssh"].reason[0])

    def test_busybox_under_linux_profile_is_warn_mismatch(self):
        # the linux script refuses a busybox userland the same way it refuses the
        # wrong OS: a profile_error → WARN ssh leaf, no metric siblings.
        stdout = ("os=Linux\nhostname=h\nprofile_error=linux profile expects a "
                  "full (non-busybox) userland but this host's df is busybox — "
                  "set 'profile: busybox'\n")
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self._run(directory, stdout)
        kids = self._kids(result)
        self.assertEqual(set(kids), {"ssh"})
        self.assertEqual(kids["ssh"].code, StatusCode.WARN)
        self.assertIn("profile mismatch", kids["ssh"].reason[0])
        self.assertIn("busybox", kids["ssh"].reason[0])

    def test_requires_host(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "metrics.sh").write_text("echo hi\n")
            with self.assertRaises(CheckError):
                HostMetricsCheck.from_config(
                    {"type": "host-metrics", "path": "/ssh", "script": "metrics.sh"},
                    Path(directory))

    def test_missing_script_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CheckError):
                HostMetricsCheck.from_config(
                    {"type": "host-metrics", "path": "/ssh", "host": "h",
                     "script": "nope.sh"}, Path(directory))


if __name__ == "__main__":
    unittest.main()
