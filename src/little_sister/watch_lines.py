"""What the /about hero says, and how a render draws from it.

The hero is the identity block with the terms she watches in orbit behind it
(`templates/about.html`, `static/js/watch.js`), and the text is most of it — the
motion is only the staging. It lives here rather than in the template because
there is far more of it than any one visit shows: a render **draws** from these
pools, so the second visit reads differently, which is what makes a page anybody
sees twice worth looking at twice.

The voice is one thing throughout: practical warnings, engineering sayings that
have been earned rather than invented, and enough dry humor to admit that all of
it has happened to somebody. Nothing here is a joke at an operator's expense —
she is on their side, and the last word is always hers.

Length is what sorts a line into a pool, and the hero spends the lengths in
order. **Signals** are one or two words — small enough to orbit, and set in
monospace because they are a machine's words. **Ticker** lines are a clause,
**observations** are a sentence with a turn in it, and the **closing** sequence
is nine short lines that arrive one at a time and end on the promise the whole
page is making. Those three are hers, and are set in her own face.
"""
from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

#: The short vocabulary: one or two words, for the labels that orbit and the
#: terms that fall. Nothing here is a sentence, because nothing here has room to
#: be read as one.
SIGNALS: tuple[str, ...] = (
    "latency", "errors", "traffic", "saturation", "availability", "durability",
    "capacity", "deployments", "rollbacks", "drift", "replication", "backups",
    "certificates", "secrets", "dependencies", "vulnerabilities", "incidents",
    "runbooks", "traces", "metrics", "logs", "alerts", "queues", "dead letters",
    "timeouts", "retries", "health checks", "rate limits", "error budgets",
    "service levels", "change failure", "recovery time",
)


@dataclass(frozen=True)
class Signal:
    """One term in orbit, and the phrase in the prose it stands for.

    ``topic`` is the seam that makes the page's own sentence light up when its
    term passes the eyes — it matches a ``data-topic`` in the story. Most terms
    carry none: they are the weather she watches in general, and nothing in the
    paragraph is about them in particular.
    """
    name: str
    topic: str = ""


#: The inner ring: the four things the story names, in the story's own order, so
#: the prose and the orbit are one list said twice — once as machine words, once
#: as English. These are the only terms that can light a phrase.
TOPICS: tuple[Signal, ...] = (
    Signal("disks", "disks"),
    Signal("jobs", "jobs"),
    Signal("advisories", "advisories"),
    Signal("actions", "actions"),
)

#: The concrete failure modes, in the order they read best: the plain ones
#: first, the wry ones last. The hero opens on a couple of these — the world's
#: noise, before her answer to it.
TICKER: tuple[str, ...] = (
    "disks fill up",
    "certificates expire",
    "secrets grow stale",
    "dependencies become vulnerable",
    "queues keep growing",
    "replicas fall behind",
    "clocks drift",
    "caches forget",
    "health checks lie",
    "retries become storms",
    "timeouts hide slow failures",
    "dead letters need readers",
    "rate limits have limits",
    "error budgets run out",
    "configuration drifts",
    "containers restart",
    "nodes become unreachable",
    "pods remain pending",
    "volumes lose patience",
    "DNS records grow old",
    "webhooks stop arriving",
    "tokens get revoked",
    "APIs change",
    "schemas disagree",
    "pipelines turn red",
    "deployments get stuck",
    "rollbacks can fail too",
    "feature flags outlive their features",
    "dashboards can be green while users see red",
    "the graph was flat because the exporter died",
    "the backup you never tested is not a backup",
    "yesterday's traffic is not tomorrow's capacity",
    "silence is not always healthy",
    "little sister is watching for you",
)

#: The long observations, in **themed sets**. A render takes a run of
#: consecutive lines from one set rather than a scatter across all of them:
#: sentences about the same thing read as a thought, and sentences about five
#: different things read as a quote wall.
OBSERVATIONS: tuple[tuple[str, ...], ...] = (
    (
        "Everything is healthy — until the health check fails.",
        "A successful deployment is not the same as a healthy service.",
        "If nobody tests the restore, it is only a theory.",
        "Retries can turn one failure into a thousand requests.",
        "An alert without an action is only a notification.",
        "Every permanent workaround eventually becomes infrastructure.",
        "Configuration drift begins with one harmless exception.",
        "The incident started long before the first alert arrived.",
        "The logs knew. Nobody asked them.",
        "The trace ended where the timeout began.",
        "The dashboard was green. The users were not.",
        "The average was fine. The tail latency was not.",
        "The queue was patient. The customers were not.",
        "The replica was running. It was also six hours behind.",
        "The certificate had warned everyone for thirty days.",
        "The error budget was spent one small failure at a time.",
        "The dependency was optional until it became unavailable.",
        "The maintenance window closed. The maintenance continued.",
        "The rollback plan worked perfectly in the document.",
        "The canary survived. The rest of the flock had other ideas.",
        "The deploy completed. The investigation began.",
        "The autoscaler reacted exactly three minutes too late.",
        "The cache improved latency and preserved yesterday's answer.",
        "The feature flag became load-bearing infrastructure.",
        "The temporary exception celebrated its third birthday.",
        "Nobody changed production. Production changed anyway.",
        "There are no small changes in a distributed system.",
        "A quiet pager is comforting. A silent pager is suspicious.",
        "Not every failure is visible from inside the service.",
        "Availability is measured where the user stands.",
    ),
    (
        "The repository says what should exist.",
        "The cluster reveals what actually exists.",
        "Desired state and actual state have stopped speaking.",
        "The pull request merged. Reconciliation has not.",
        "The manifest changed. The running workload did not.",
        "The image tag stayed the same. The image did not.",
        "Latest is not a version.",
        "Immutable infrastructure still depends on mutable humans.",
        "A green pipeline proves that the pipeline is green.",
        "The artifact was built once and configured many times.",
        "The deployment succeeded everywhere except production.",
        "The policy passed yesterday.",
        "The secret was rotated. One consumer missed the memo.",
        "The controller will keep trying. That is both a promise and a warning.",
        "Manual fixes disappear during the next reconciliation.",
        "If it is not declared, it cannot reliably be reproduced.",
        "Drift is a message from reality.",
        "Every emergency change deserves a later pull request.",
    ),
    (
        "The first priority is mitigation. Curiosity can wait.",
        "Restore service before restoring pride.",
        "An incident has no respect for ownership boundaries.",
        "The page arrived. Context did not.",
        "The runbook ended one step before the interesting part.",
        "The alert fired exactly as configured.",
        "The symptom recovered. The cause remained.",
        "A resolved alert is not always a resolved incident.",
        "Today's near miss is tomorrow's runbook.",
        "Blameless does not mean lessonless.",
        "The postmortem begins where certainty ends.",
        "The best page is the one prevented during office hours.",
        "Good alerts ask for action.",
        "If every alert is urgent, none of them are.",
        "little sister wakes you only when staying asleep would be worse.",
    ),
    (
        "Metrics tell you that something changed.",
        "Logs tell you what happened.",
        "Traces tell you where the time went.",
        "Profiles tell you what kept the machine busy.",
        "Events tell you when the story changed direction.",
        "Context turns telemetry into evidence.",
        "Cardinality grows quietly.",
        "Sampling always leaves something unseen.",
        "Missing data is data.",
        "No signal is healthy unless silence was expected.",
        "Instrument the boundaries.",
        "Measure outcomes, not only activity.",
        "Monitor the user journey, not merely the process.",
        "Watch the dependency you do not control.",
        "A dashboard should answer a question.",
        "An alert should suggest an action.",
        "A service-level objective makes reliability discussable.",
        "The four golden signals never sleep.",
        "little sister watches the signals while you watch the service.",
    ),
)

#: The ending, and the only pool that is never drawn from or reordered: nine
#: lines arriving one at a time, from what is true of every system to what she
#: promises about this one. The last line is the brand sentence, which is where
#: the whole page has been going.
CLOSING: tuple[str, ...] = (
    "Systems change.",
    "Failures happen.",
    "Signals appear.",
    "I keep watch.",
    "You decide where I look.",
    "You decide what matters.",
    "When something needs you, I will tell you.",
    "Until then, rest easy.",
    "little sister is watching for you.",
)

#: How many terms the outer ring carries — the whole field is eleven, four of
#: them the story's own. It is a function of how wide the rings are: fewer reads
#: as an empty orbit, more as a word cloud, and the number moves with the
#: geometry rather than being a taste.
OUTER_SIGNALS = 7

#: What she says while the hero settles, by kind: two clauses at ticker length,
#: one observation, and then the ending — which is never drawn from. The lengths
#: differ on purpose. A page that speaks in one rhythm stops being read.
OPENING_CLAUSES = 2
OPENING_OBSERVATIONS = 1


def draw(pool: Sequence[str], count: int,
         rng: random.Random | None = None) -> tuple[str, ...]:
    """``count`` lines from ``pool``, in the pool's own order, without repeats.

    Order is kept because these pools are written in an order — the ticker
    builds, the observations pair up — and a shuffle would read as a shuffle. A
    pool shorter than ``count`` simply gives what it has.
    """
    chooser = rng or random
    if count >= len(pool):
        return tuple(pool)
    picked = chooser.sample(range(len(pool)), count)
    return tuple(pool[index] for index in sorted(picked))


def observations(count: int,
                 rng: random.Random | None = None) -> tuple[str, ...]:
    """``count`` lines from **one** themed set, consecutive where they can be.

    From one set rather than across all of them because sentences about the same
    thing read as a thought, and sentences about five different things read as a
    wall of quotations.
    """
    chooser = rng or random
    lines = chooser.choice(OBSERVATIONS)
    if count >= len(lines):
        return lines
    start = chooser.randrange(len(lines) - count + 1)
    return lines[start:start + count]


def rings(rng: random.Random | None = None) -> tuple[tuple[Signal, ...], ...]:
    """The two orbits: the story's own four inside, drawn signals outside.

    The inner ring is fixed because it is the one the paragraph answers to; the
    outer one is a draw, so the page's weather differs between visits.
    """
    drawn = draw(SIGNALS, OUTER_SIGNALS, rng)
    return (tuple(Signal(name) for name in drawn), TOPICS)


def says(rng: random.Random | None = None) -> tuple[str, ...]:
    """What the hero says, in order: clauses, then a sentence, then the ending.

    Short to long, and then the nine lines that are always the same — the page
    opens on the world's noise and closes on her promise about it, and having
    said that it stops. Nothing here loops: a page that never finishes talking
    is a page nobody finishes reading.
    """
    return (draw(TICKER, OPENING_CLAUSES, rng)
            + observations(OPENING_OBSERVATIONS, rng)
            + CLOSING)
