"""This instance, named — one mark for the running process (ADR-0074).

Until this module there was **no notion of an instance** in the library at all.
Nothing named the running process, and ``/system`` reported what was installed
without ever saying *which installation this is*. That was fine while an
installation was a directory on a machine somebody had ssh'd into.

It stopped being fine when state started leaving the machine. ``little-sister-aws``
had to invent a mark of its own to answer *did I write this?* about an object in a
bucket, that mark went into somebody's S3 prefix and onto a status line, and the
next package with the same question would have invented a second one. So the
library owns it, and there is one.

**The shape: ``<name>:<pid>:<started>:<tag>``.**

* ``name`` is the deployment's, from ``instance:`` in ``config/settings.yaml``, and
  the **hostname** where it says nothing — which in a container is already the task
  or pod name, so the default is usually the name somebody would have chosen.
* ``pid`` and ``started`` are for the human: together they are what turns a mark on
  a page into a process somebody can find, and ``started`` says how long this one
  has been up without anybody having to subtract two timestamps. It is UTC in the
  **basic** ISO form, because the separator here is a colon and the extended form
  carries three of its own.
* ``tag`` is eight random hex characters drawn once, and it is not decoration: it
  is what makes an **equality test** on the mark sound. Two containers of one
  deployment share a configured name, run as pid 1, and start in the same second —
  so without it two live processes could be handed one mark, and a reader comparing
  marks would take a second writer for itself. That failure is silent, which is why
  the library appends the tag rather than trusting the name to be unique.

The tag is also what makes ``instance:`` **safe to offer**. A name a deployment
chooses is far more readable than ``ip-10-0-3-14`` in a fleet of identical hosts,
and the reason to withhold it — two instances given one name — is answered by the
library adding uniqueness the deployment cannot take away.

**The mark is never parsed.** It is compared for equality and printed. Nothing here
promises the parts stay in this order or stay four; what is promised is that two
processes never share a mark and that one process's mark never changes while it
runs.

**Resolved once, on first use.** A mark that changed mid-process would break the
only thing it is for, so :func:`this_instance` memoises — but it resolves when it is
first *asked*, not when this module is imported, and that distinction is load-bearing.
The name comes from the settings, reading the settings needs a configuration root, and
a package that imports this module in its own module body would otherwise need that
root to exist at **import** time. `little-sister-aws` is exactly such a package. So
the configuration is reached inside :func:`resolve` and nowhere else, and importing
this module costs nothing.
"""
from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass

from little_sister import instants, self_report
from little_sister.reasons import plain

#: The longest configured name. Long enough for a deployment's own naming scheme,
#: short enough that the mark stays readable in a table cell and in a log line.
MAX_NAME = 64

#: What a configured name may not contain: the mark's own separator, and
#: whitespace, which would make one mark look like two words on a page.
_REFUSED = (":", " ", "\t", "\n")


@dataclass(frozen=True)
class Instance:
    """One running process, as everything that has to name one sees it."""

    name: str
    pid: int
    #: UTC, basic ISO (``20260905T090000Z``) — see the module docstring.
    started: str
    #: Eight random hex characters, drawn once per process.
    tag: str

    @property
    def mark(self) -> str:
        """The whole of it, joined. This is what a package writes down."""
        return f"{self.name}:{self.pid}:{self.started}:{self.tag}"


def _valid_name(value: object) -> str:
    """Coerce a configured instance name, falling back to the hostname with a
    warning — the same bargain every other setting makes (ADR-0074 §4).

    A refusal here would be the wrong trade: nothing about this name is
    load-bearing, since the tag carries the uniqueness, and refusing to start over
    a cosmetic label would make the mark more dangerous than not having one.
    """
    host = socket.gethostname()
    name = str(value).strip()
    if not name:
        self_report.startup.note(
            "instance",
            plain(f"instance: was written and left empty; the hostname {host!r} "
                  f"is in use"))
        return host
    for refused in _REFUSED:
        if refused in name:
            self_report.startup.note(
                "instance",
                plain(f"instance: {name!r} may not contain {refused!r} — the mark "
                      f"joins its parts with ':' and is read as one word; the "
                      f"hostname {host!r} is in use"))
            return host
    if len(name) > MAX_NAME:
        self_report.startup.note(
            "instance",
            plain(f"instance: {name!r} is longer than {MAX_NAME} characters; the "
                  f"hostname {host!r} is in use"))
        return host
    return name


def resolve() -> Instance:
    """Build an identity from the configuration as it stands now.

    Public and **not** memoised: :func:`this_instance` is the one everything uses,
    and this is what a test calls with its own settings in place.
    """
    # Imported here rather than at the top: reading the settings needs a
    # configuration root, and importing this module must not. See the module
    # docstring.
    from little_sister.config import config

    return Instance(
        name=_valid_name(config.instance) if config.instance
        else socket.gethostname(),
        pid=os.getpid(),
        started=instants.now().strftime("%Y%m%dT%H%M%SZ"),
        tag=uuid.uuid4().hex[:8])


#: This process, once it has been asked for. Never reset outside a test.
_RESOLVED: Instance | None = None


def this_instance() -> Instance:
    """This process\'s identity — resolved on the first call and never again."""
    global _RESOLVED
    if _RESOLVED is None:
        _RESOLVED = resolve()
    return _RESOLVED


__all__ = ["MAX_NAME", "Instance", "resolve", "this_instance"]
