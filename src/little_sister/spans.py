"""How this project writes a span of time.

Three surfaces render one: how long a check *took*, how long until it runs
*again*, how long ago something *was*. They are the same quantity — a number of
seconds — and the temptation is to format each where it is displayed, which is
what happened: the system page grew `f"{seconds:.0f} s"` in one cell and
`f"{seconds}s"` inline in a template, so a fifteen-minute wait read `in 812s` and
a two-minute run read `115 s`. Both are correct and neither is readable, and no
amount of care in one of them fixes the other.

So the renderings live here, together, and every surface calls one of them. That
is also why this module is on the **public API surface** (architecture.md §11): a
check type outside this repository writes durations into its reason lines — *"the
backup took 2h 7m"* — and a plugin that formatted its own would drift from the
page it renders onto. :func:`~little_sister.checks.parse_duration` reads a span
from a config; these write one to a screen.

**Three renderings, because there are three readings, and they must not be
merged.**

:func:`format_span` is for a span whose **size is the information** — a measured
runtime, a countdown. It keeps roughly three significant figures at every scale,
so it changes units as the value grows rather than letting the number grow: a
millisecond run and a two-day run are both four or five characters wide.

:func:`coarse_span` is for a span whose size is **approximately** the information
— *how long ago*, *how much is left*. It states the largest one or two units and
stops, and it is deliberately lossy: it is used where the value is a **floor**
that has to stay true on a page nobody is re-rendering (`> 2m ago`), and a floor
that names seconds stops being one the moment it is read.

:func:`format_duration` is for a span nobody measured: a **configured** interval,
written back in the units the config wrote it in — `900` is `15m`, because that is
what somebody typed. It is the exact opposite reading to :func:`format_span`,
which would call the same number `15m` and the next one `1m 30s` where the config
says `90s`. Keeping it here rather than in the one template filter that used to
own it is what lets a *document* state a check's frequency and say what the page
says.

All three take seconds, and all three are total functions on a number: no
exception, no `None` handling beyond what is written, because a formatter that can
raise turns a display detail into a 500.

**And one instant, beside the three spans.** :func:`local_time` writes a moment the
way every page does — in the `timezone` and `time_format` of `settings.yaml` — and
it is here for the same reason the spans are: a plugin that writes *when* into a
line (*the lease lapsed at …*) must say it in the words of the page it renders
onto, and a `GMT` beside the page's `Europe/Berlin` was the first thing a plugin
did when it had nothing here to call. The application's own rendering delegates
here rather than the other way round.
"""
from __future__ import annotations

from datetime import datetime

#: The public face, and the code half of the architecture.md §11 promise: a name
#: added here without being written into that block fails `test_public_surface`.
__all__ = ["coarse_span", "format_duration", "format_span", "local_time"]

_MINUTE = 60
_HOUR = 3600
_DAY = 86400
_WEEK = 604800


def format_span(seconds: float | None, *, none: str = "—") -> str:
    """A measured span, at roughly three significant figures whatever its size.

    The ladder, and what each rung is for:

    ======================  ==============  ====================================
    input                   renders as      why this rung
    ======================  ==============  ====================================
    ``None``                ``—``           nothing has been measured yet
    ``0.412``               ``412 ms``      a fast check is milliseconds, and
                                            ``0 s`` would say it took no time
    ``3.14159``             ``3.1 s``       one decimal, where it still separates
                                            two runs
    ``42.7``                ``43 s``        past ten seconds a decimal is noise
    ``115``                 ``1m 55s``      **the reason this function exists**
    ``7620``                ``2h 7m``       minutes still matter within an hour
    ``97200``               ``1d 3h``       days, and the hour that qualifies it
    ======================  ==============  ====================================

    A **zero lower unit is dropped** — 120 seconds is ``2m``, not ``2m 0s`` — so
    the second unit appears exactly when it says something. Nothing below the
    second unit is ever shown: ``1m 55s`` does not become ``1m 55.3s``, because
    three significant figures is the whole rule and a run that took a minute is
    not measured to the millisecond in any meaningful sense.

    Negative input is rendered as ``0 s`` rather than a negative span. It happens:
    a countdown read a moment after its deadline, a clock stepping backwards.
    ``-3 s`` on a dashboard reads as a bug in the page rather than as the passing
    instant it is.

    ``none`` overrides what an absent value renders as, for a caller with a better
    word than the em dash.
    """
    if seconds is None:
        return none
    if seconds <= 0:
        return "0 s"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 10.0:
        return f"{seconds:.1f} s"
    if seconds < _MINUTE:
        return f"{seconds:.0f} s"
    # From here the value is whole seconds: rounding first means 119.6 seconds
    # renders `2m` rather than `1m 59s`, which is what the second-level display
    # of every rung above it already promises.
    total = round(seconds)
    if total < _HOUR:
        minutes, rest = divmod(total, _MINUTE)
        return f"{minutes}m {rest}s" if rest else f"{minutes}m"
    if total < _DAY:
        hours, rest = divmod(total, _HOUR)
        minutes = rest // _MINUTE
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, rest = divmod(total, _DAY)
    hours = rest // _HOUR
    return f"{days}d {hours}h" if hours else f"{days}d"


def format_duration(seconds: int | None, *, none: str = "—") -> str:
    """A **configured** interval, in the units the configuration wrote it in:
    ``900`` is ``15m``, ``3600`` is ``1h``, ``86400`` is ``1d``, ``604800`` is
    ``1w``, ``90`` is ``90s``.

    The rule is exact division, largest unit first, and no second unit ever — a
    configured interval is one number somebody typed, and ``1h 1m`` is not what
    they typed. :func:`format_span` answers the other question about the same
    seconds (*how long did this take*) and answers it differently on purpose;
    picking the wrong one of the two is how a page ends up claiming a check runs
    every ``1m 30s``.

    Zero and ``None`` are the same answer here — ``none``, an em dash by default —
    because a frequency of zero is not an interval, it is the absence of one.
    """
    if not seconds:
        return none
    if seconds % _WEEK == 0:
        return f"{seconds // _WEEK}w"
    if seconds % _DAY == 0:
        return f"{seconds // _DAY}d"
    if seconds % _HOUR == 0:
        return f"{seconds // _HOUR}h"
    if seconds % _MINUTE == 0:
        return f"{seconds // _MINUTE}m"
    return f"{seconds}s"


def coarse_span(seconds: float) -> str:
    """A span as its largest one or two units: ``2d 3h`` / ``5h`` / ``12m``.

    Deliberately lossy, and its floor is the point. Both callers state a bound
    rather than a measurement — *how long ago* a page's data was fetched, *how
    much is left* of a maintenance window — on surfaces that are not re-rendered
    while somebody reads them. A bound that names seconds is out of date before
    the sentence ends; ``> 2m ago`` starts true and stays true however long the
    window sits open.

    Under a minute there is no bound worth stating, so it says ``< 1m`` and the
    caller decides whether to phrase it at all — :func:`little_sister.app._since`
    substitutes a clock time there, because *less than a minute ago* is exactly
    the reading that rots.

    For a span whose exact size is the information, use :func:`format_span`.
    """
    total = int(seconds)
    if total >= _DAY:
        days, rest = divmod(total, _DAY)
        hours = rest // _HOUR
        return f"{days}d {hours}h" if hours else f"{days}d"
    if total >= _HOUR:
        hours, rest = divmod(total, _HOUR)
        minutes = rest // _MINUTE
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if total >= _MINUTE:
        return f"{total // _MINUTE}m"
    return "< 1m"


def local_time(moment: datetime, fmt: str | None = None) -> str:
    """One instant, in the configured timezone and ``time_format``; ``fmt``
    overrides the format and never the zone.

    A naive ``moment`` is read as the machine's local time, which is what a
    timestamp somebody built from ``datetime.now()`` means; an aware one is
    converted. The configuration is read at the call, not at import — this module
    has no imports of its own and must keep it that way, because the configuration
    reads the settings file when *it* is imported and imports the limits that
    import this.
    """
    from little_sister.config import config
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(config.tzinfo).strftime(fmt or config.time_format)
