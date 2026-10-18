"""The template held against the family's vocabularies (ADR-0126): lines rendered
through ``Check.line`` from fixtures shaped like the records the family's types keep
today, and said as those types say them today — ``little-sister-github`` 0.1.11's
``actions`` lines, ``little-sister-aws`` 0.1.6's pipeline line with its stale-success
judgment and an execution said for the record alone (ADR-0111), and
``little-sister-wiz`` 0.1.3's issue line.

None of those packages is a dependency of the library, so what each writes today is
copied here as it stands in that release (the ``_today_*`` functions), beside forms a
type could declare for it, and every shape the copied code writes is rendered both
ways and compared. The forms are this suite's and not those packages': each decides
its own when it adopts, in a release of its own. What the comparison holds is the
design: that a form the grading names, with its segments, says what the code says for
every shape it has — the ``actions`` line in two forms, Wiz's issue line in one — with
the words a type hands over and nothing computed in the template.
"""
from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import TestCase

from little_sister.checks import Check, Measurement
from little_sister.checks.base import CheckResult
from little_sister.reasons import plain
from little_sister.render import render_markdown
from little_sister.status import StatusCode

HERE = Path(".")


def _link(text: str, url: str) -> str:
    """The link ``little-sister-github`` writes, as it stands."""
    return f"[{text}]({url})" if url else text


def _declared(entries: Mapping[str, tuple[str, object]]) -> dict[str, object]:
    """Words or fields as a type declares them: each one sentence and an example."""
    return {name: {"sentence": sentence, "example": example}
            for name, (sentence, example) in entries.items()}


def _type(forms: Mapping[str, tuple[str, str]],
          words: Mapping[str, tuple[str, object]],
          fields: Mapping[str, tuple[str, object]]) -> Check:
    """A check of a type declaring ``forms`` (each a sentence and its default text),
    ``words`` and ``fields``, built as any check is."""
    declared_forms = {name: {"sentence": sentence, "text": text}
                      for name, (sentence, text) in forms.items()}

    class _Shaped(Check):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(line_forms=declared_forms, line_words=_declared(words),
                             line_fields=_declared(fields), **kwargs)

        def measure(self) -> Sequence[Measurement]:
            return ()

        def grade(self, measurements: Sequence[Measurement],
                  now: datetime) -> CheckResult:
            return CheckResult(StatusCode.OK)

    return _Shaped.from_config({"path": "/shapes"}, HERE)


# --- little-sister-github 0.1.11: the actions aspect -------------------------------

RUN_41 = "https://github.example.org/acme/shop/actions/runs/901"
RUN_42 = "https://github.example.org/acme/shop/actions/runs/902"
WORKFLOW_PAGE = "https://github.example.org/acme/shop/actions/workflows/nightly.yml"


def _today_actions(name: str, record: Mapping[str, Any]) -> str:
    """``GitHubCheck._action_text``, as it stands — the repository's name, which it
    reads off the ``Repo`` it is handed, handed in as ``name``."""
    where = (f"{plain(name)} ({plain(str(record['branch']))}) / "
             f"{plain(str(record['workflow']))}")
    completed = record.get("completed")
    running = record.get("running")
    completed_url = (completed["url"] or "") if completed else ""
    running_url = (running["url"] or "") if running else ""
    run_number = (completed["run_number"] or 0) if completed else 0
    verdict = record["verdict"]
    if verdict is None:
        text = f"{_link(where, running_url)}: no completed run"
    else:
        number = f" (#{run_number})" if run_number else ""
        text = f"{_link(where, completed_url)}: {verdict}{number}"
    if running:
        running_number = running["run_number"] or 0
        label = f"#{running_number} running" if running_number else "running"
        text += f" · {_link(label, running_url)}"
    return text


#: ``GitHubCheck._DISABLED_WORDS``, as it stands.
_DISABLED_WORDS = {
    "disabled_manually": "disabled manually",
    "disabled_inactivity": "disabled by GitHub after 60 days without "
                           "repository activity",
    "disabled_fork": "disabled by GitHub on this fork",
}


def _today_disabled(name: str, record: Mapping[str, Any]) -> str:
    """``GitHubCheck._disabled_text``, as it stands."""
    where = f"{plain(name)} / {plain(str(record['workflow']))}"
    state = str(record["state"])
    word = _DISABLED_WORDS.get(state, f"disabled ({plain(state)})")
    return f"{_link(where, record['url'] or '')}: {word}, no runs read"


_RUNNING = "{?running: · [{?#{running.run_number} }running]({running.url})}"


def _github() -> Check:
    return _type(
        forms={
            "actions.verdict": (
                "The verdict of the newest run that has one, and a run in flight "
                "after it.",
                "[{line.name} ({branch}) / {workflow}]({completed.url}): {verdict}"
                "{? (#{completed.run_number})}" + _RUNNING),
            "actions.no_verdict": (
                "No run of the workflow on its branch has a verdict yet.",
                "[{line.name} ({branch}) / {workflow}]({running.url}): no completed "
                "run" + _RUNNING),
            "actions.disabled": (
                "The workflow is switched off, and no run of it was read.",
                "[{line.name} / {workflow}]({url}): {line.state}, no runs read")},
        words={"name": ("The repository's name, without its owner's.", "shop"),
               "state": ("What the workflow's state says, in GitHub's words.",
                         "disabled manually")},
        fields={"branch": ("The branch the runs are read on.", "main"),
                "workflow": ("The workflow's name.", "CI"),
                "verdict": ("The word the line says for the newest verdict.",
                            "passed"),
                "url": ("The page a disabled workflow is switched on from.",
                        WORKFLOW_PAGE),
                "completed.url": ("The page of the run the verdict is of.", RUN_41),
                "completed.run_number": ("That run's number.", 41),
                "running": ("The run in flight, where there is one.", "{…}"),
                "running.url": ("The page of the run in flight.", RUN_42),
                "running.run_number": ("Its number.", 42)})


class GitHubActionsTests(TestCase):
    """The ``actions`` line in two forms — a verdict, or none yet — where its code
    writes eight shapes, and a disabled workflow's line with GitHub's word for its
    state as a word (ADR-0126 decisions 2 and 3)."""

    COMPLETED = (None, {"url": RUN_41, "run_number": 41},
                 {"url": None, "run_number": 41}, {"url": RUN_41, "run_number": None})
    RUNNING = (None, {"url": RUN_42, "run_number": 42},
               {"url": RUN_42, "run_number": None}, {"url": None, "run_number": 42})

    def test_every_shape_says_what_the_code_says(self) -> None:
        check = _github()
        for verdict, completed, running in itertools.product(
                (None, "passed", "failed"), self.COMPLETED, self.RUNNING):
            if verdict is not None and completed is None:
                continue
            record: dict[str, Any] = {
                "aspect": "actions", "kind": "run", "repository": "acme/shop",
                "repository_id": 7, "workflow": "Build *nightly* [beta]",
                "workflow_id": 11, "file": "ci.yml", "branch": "feat/x_y",
                "verdict": verdict, "at": "2026-10-11T08:00:00Z"}
            if completed is not None:
                record["completed"] = {**completed, "status": "completed",
                                       "started": "2026-10-11T08:00:00Z"}
            if running is not None:
                record["running"] = {**running, "status": "in_progress",
                                     "started": "2026-10-11T09:00:00Z"}
            form = "actions.no_verdict" if verdict is None else "actions.verdict"
            with self.subTest(verdict=verdict, completed=completed, running=running):
                line = check.line(form, Measurement(record=record), slug="ci",
                                  words={"name": "shop"})
                self.assertEqual(line.text, _today_actions("shop", record))

    def test_the_line_as_it_reads(self) -> None:
        record = {"workflow": "CI", "branch": "main", "verdict": "passed",
                  "completed": {"url": RUN_41, "run_number": 41},
                  "running": {"url": RUN_42, "run_number": 42}}
        line = _github().line("actions.verdict", Measurement(record=record),
                              slug="ci", words={"name": "shop"})
        self.assertEqual(line.text, f"[shop (main) / CI]({RUN_41}): passed (#41) · "
                                    f"[#42 running]({RUN_42})")

    def test_a_disabled_workflow_says_why_it_is_off(self) -> None:
        check = _github()
        for state, url in itertools.product(
                (*_DISABLED_WORDS, "disabled_policy", "disabled*odd"),
                (WORKFLOW_PAGE, None)):
            record = {"aspect": "actions", "kind": "disabled",
                      "repository": "acme/shop", "workflow": "Nightly *build*",
                      "state": state, "url": url}
            word = _DISABLED_WORDS.get(state, f"disabled ({state})")
            with self.subTest(state=state, url=url):
                line = check.line("actions.disabled", Measurement(record=record),
                                  slug="ci", words={"name": "shop", "state": word})
                self.assertEqual(line.text, _today_disabled("shop", record))


# --- little-sister-aws 0.1.6: a pipeline, and an execution for the record ----------

PIPELINE = "https://console.example.org/codesuite/codepipeline/pipelines/deploy-shop"


def _today_pipeline(label: str, link: str, verdict: str,
                    in_flight: Sequence[str]) -> str:
    """``AwsCheck._pipeline_entry``'s text, as it stands — its parts handed in: the
    phrase of the execution whose verdict the line keeps, and one per status of the
    executions in flight."""
    parts = ([verdict] if verdict else []) + list(in_flight)
    return f"[{plain(label)}]({link}): {' · '.join(parts)}"


def _today_verdict(status: str, age: str | None, stale: bool,
                   sentence: str) -> str:
    """``AwsCheck._verdict_of``'s phrase, as it stands, the age written already, as
    ``coarse_span`` writes one: a success older than its rule allows is said as
    such, with the rule's own sentence where it has one."""
    when = f", started {age} ago" if age is not None else ""
    phrase = f"{plain(status)}{when}"
    if stale:
        phrase = f"{plain(status)}, but that run started {age} ago"
        if sentence:
            phrase += f" — {plain(sentence)}"
    return phrase


def _today_execution(status: str, began: str | None, age: str | None) -> str:
    """``AwsCheck._execution_entry``'s sentence, as it stands: the status — and, of
    an execution in flight past ``max_run_time``, when it began, ``started`` or
    ``retried``, with its age written already."""
    if began is None:
        return plain(status)
    return f"{plain(status)}, {began} {age} ago, past max_run_time"


_IN_FLIGHT = "{? · {line.in_flight}}"


def _aws() -> Check:
    return _type(
        forms={
            "pipeline.verdict": (
                "The status of the execution the line keeps, and when it started.",
                "[{line.label}]({line.link}): {status}{?, started {line.age} ago}"
                + _IN_FLIGHT),
            "pipeline.stale": (
                "That execution succeeded, longer ago than a rule allows.",
                "[{line.label}]({line.link}): {status}, but that run started "
                "{line.age} ago{? — {line.why}}" + _IN_FLIGHT),
            "pipeline.never_run": (
                "The pipeline has never been executed.",
                "[{line.label}]({line.link}): never run" + _IN_FLIGHT),
            "pipeline.in_flight": (
                "Every execution read is in flight.",
                "[{line.label}]({line.link}): {line.in_flight}"),
            "pipeline.execution": (
                "An execution the line does not keep, for the record alone.",
                "{status}"),
            "pipeline.execution_overran": (
                "Such an execution, in flight for longer than max_run_time.",
                "{status}, {line.began} {line.age} ago, past max_run_time")},
        words={"label": ("The pipeline's name, after a display rule shortened it.",
                         "shop"),
               "link": ("The pipeline's executions in the console, wrapped in the "
                        "account's template.", PIPELINE),
               "age": ("How long ago it started, as the grading measured it.", "2d"),
               "why": ("The rule's own sentence, where it has one.",
                       "Deploys run nightly."),
               "in_flight": ("What is in flight, one phrase per status.",
                             "InProgress, started 5m ago"),
               "began": ("How an execution in flight began: started, or retried.",
                         "started")},
        fields={"status": ("The execution's status, in CodePipeline's words.",
                           "Succeeded"),
                "name": ("The pipeline's name.", "deploy-shop"),
                "started": ("When the execution started.", "2026-10-09T06:00:00Z")})


def _execution(status: str | None) -> Measurement:
    return Measurement(
        record={"aspect": "codepipeline", "kind": "pipeline", "account": "example",
                "region": "eu-example-1", "name": "deploy-shop", "execution": "e-1",
                "status": status, "started": "2026-10-09T06:00:00Z",
                "duration_s": 300, "at": "2026-10-09T06:00:00Z"},
        subject="codepipeline:example:eu-example-1:deploy-shop", identity="e-1")


class AwsPipelineTests(TestCase):
    """A pipeline's line joins what was read to the grading's judgment —
    ``Succeeded, but that run started 2d ago —`` and a rule's own sentence — and
    says a time as an age: the judgment is a form, its values are words, and the
    executions in flight are one word, the one thing a form cannot write (ADR-0126
    decisions 2 and 3)."""

    #: The line's verdict, by the form the grading names for it: a status, an age,
    #: whether it is stale, and the rule's sentence.
    VERDICTS = (
        ("pipeline.verdict", "Succeeded", "3h", False, ""),
        ("pipeline.verdict", "Failed", "1h", False, ""),
        ("pipeline.verdict", "Succeeded", None, False, ""),
        ("pipeline.stale", "Succeeded", "2d", True, ""),
        ("pipeline.stale", "Succeeded", "2d", True,
         "Deploys run *nightly*; a success older than a day means they stopped."))
    IN_FLIGHT = ((), ("InProgress, started 5m ago",),
                 ("InProgress, started 5m ago",
                  "2 Stopping, the oldest started 1h ago"))

    def test_every_shape_says_what_the_code_says(self) -> None:
        check = _aws()
        for (form, status, age, stale, sentence), in_flight in itertools.product(
                self.VERDICTS, self.IN_FLIGHT):
            words: dict[str, object] = {
                "label": "shop", "link": PIPELINE, "age": age, "why": sentence,
                "in_flight": " · ".join(in_flight)}
            with self.subTest(form=form, age=age, sentence=sentence,
                              in_flight=in_flight):
                line = check.line(form, _execution(status), slug="pipeline",
                                  words=words)
                self.assertEqual(line.text, _today_pipeline(
                    "shop", PIPELINE, _today_verdict(status, age, stale, sentence),
                    in_flight))

    def test_never_run_and_all_in_flight(self) -> None:
        check = _aws()
        for in_flight in self.IN_FLIGHT:
            words: dict[str, object] = {"label": "shop", "link": PIPELINE,
                                        "in_flight": " · ".join(in_flight)}
            with self.subTest(in_flight=in_flight):
                line = check.line("pipeline.never_run", _execution(None),
                                  slug="pipeline", words=words)
                self.assertEqual(line.text, _today_pipeline(
                    "shop", PIPELINE, "never run", in_flight))
                if in_flight:
                    line = check.line("pipeline.in_flight", _execution("InProgress"),
                                      slug="pipeline", words=words)
                    self.assertEqual(line.text, _today_pipeline(
                        "shop", PIPELINE, "", in_flight))

    def test_the_stale_success_as_it_reads(self) -> None:
        line = _aws().line(
            "pipeline.stale", _execution("Succeeded"), slug="pipeline",
            code=StatusCode.WARN,
            words={"label": "shop", "link": PIPELINE, "age": "2d",
                   "why": "Deploys run nightly."})
        self.assertEqual(line.text, f"[shop]({PIPELINE}): Succeeded, but that run "
                                    f"started 2d ago — Deploys run nightly.")
        self.assertEqual((line.code, line.form, line.subject),
                         (StatusCode.WARN, "pipeline.stale",
                          "codepipeline:example:eu-example-1:deploy-shop"))

    def test_an_execution_is_said_for_the_record_alone_the_same_way(self) -> None:
        check = _aws()
        for status, began, age, code in (
                ("Failed", None, None, StatusCode.ERROR),
                ("Succeeded", None, None, StatusCode.OK),
                ("InProgress", "started", "3h", StatusCode.ERROR),
                ("InProgress", "retried", "2h", StatusCode.ERROR)):
            form = ("pipeline.execution" if began is None
                    else "pipeline.execution_overran")
            reading = _execution(status)
            with self.subTest(status=status, began=began):
                kept = CheckResult(StatusCode.OK, for_record=[check.line(
                    form, reading, slug="execution", code=code,
                    words={"began": began, "age": age})]).for_record
                self.assertEqual([(line.text, line.code, line.data) for line in kept],
                                 [(_today_execution(status, began, age), code,
                                   dict(reading.record))])


# --- little-sister-wiz 0.1.3: an issue ---------------------------------------------

def _issue_link(issue_id: str, severity: str) -> str:
    """An issue's page, shaped as ``little-sister-wiz``'s ``_issue_link`` shapes one
    — a fragment of nested parentheses — on a host of this suite's."""
    return ("https://issues.example.org/issues#~(filters~(status~(equals~(~'OPEN~"
            f"'IN_PROGRESS))~severity~(equals~(~'{severity.upper()})))~issue~"
            f"'{issue_id})")


def _today_issue(record: Mapping[str, Any]) -> str:
    """``_issue_entry``'s text, as it stands."""
    control_name = str(record["control_name"] or record["control_id"] or "issue")
    name = str(record["entity_name"] or "")
    kind = str(record["entity_type"] or "").replace("_", " ").lower()
    issue_id = str(record["id"] or "")
    flagged = (f"[{plain(control_name)}]"
               f"({_issue_link(issue_id, str(record['severity']))})"
               if issue_id else plain(control_name))
    if name:
        affected = f"**{plain(name)}**"
        if kind:
            affected += f" ({plain(kind)})"
        text = f"{affected} — {flagged}"
    else:
        text = flagged
    if str(record["status"] or "").upper() == "IN_PROGRESS":
        text += " · *in progress*"
    return text


def _wiz() -> Check:
    return _type(
        forms={"issue": (
            "One issue, led by the entity it was found on.",
            "{?**{entity_name}**{? ({line.kind})} — }[{line.control}]({line.link})"
            "{?line.in_progress: · *in progress*}")},
        words={"kind": ("The entity's kind, as a reader says it.", "storage bucket"),
               "control": ("The control that flagged the issue, or its id where it "
                           "has no name.", "Bucket allows public reads"),
               "link": ("The issue's page.", _issue_link("i-1", "high")),
               "in_progress": ("Somebody is working on the issue.", True)},
        fields={"entity_name": ("The entity the issue was found on.", "shop-assets")})


def _issue_words(record: Mapping[str, Any]) -> dict[str, object]:
    """What a grading would hand over with an issue's line."""
    issue_id = str(record["id"] or "")
    return {"kind": str(record["entity_type"] or "").replace("_", " ").lower(),
            "control": str(record["control_name"] or record["control_id"] or "issue"),
            "link": _issue_link(issue_id, str(record["severity"])) if issue_id else "",
            "in_progress": str(record["status"] or "").upper() == "IN_PROGRESS"}


class WizIssueTests(TestCase):
    """An issue's line, shaped by flags and a word derived in code, in one form
    where flat ones would need twelve (ADR-0126 decision 3) — its link a fragment of
    nested parentheses, written as it reads (decision 4)."""

    def test_every_shape_says_what_the_code_says(self) -> None:
        check = _wiz()
        for name, kind, issue_id, status, control in itertools.product(
                ("shop-assets", "", None), ("STORAGE_BUCKET", None),
                ("i-1", None), ("IN_PROGRESS", "OPEN"),
                ("Bucket allows *public* reads", None)):
            record = {"kind": "issue", "id": issue_id, "severity": "HIGH",
                      "status": status, "control_id": "ctl-1",
                      "control_name": control, "entity_name": name,
                      "entity_type": kind}
            with self.subTest(record=record):
                line = check.line("issue", Measurement(record=record), slug="issue",
                                  words=_issue_words(record))
                self.assertEqual(line.text, _today_issue(record))

    def test_the_line_as_it_reads_and_where_its_link_leads(self) -> None:
        record = {"kind": "issue", "id": "i-1", "severity": "HIGH",
                  "status": "IN_PROGRESS", "control_id": "ctl-1",
                  "control_name": "Bucket allows public reads",
                  "entity_name": "shop-assets", "entity_type": "STORAGE_BUCKET"}
        line = _wiz().line("issue", Measurement(record=record), slug="issue",
                           words=_issue_words(record))
        link = _issue_link("i-1", "HIGH")
        self.assertEqual(line.text, f"**shop-assets** (storage bucket) — [Bucket "
                                    f"allows public reads]({link}) · *in progress*")
        self.assertIn(f'href="{link}"', str(render_markdown(line.text)))
