"""WSGI entrypoint: what this installation registers before the app is built.

Every deployment in this family has one of these, and until the identity seam landed
this repository was the exception — it registers no check types of its own, so it
served ``little_sister.app:app`` directly and the shape its own documentation
describes was the one shape it did not run. It has two things to register now, and
between them they are **every way into this instance**:

* the **built-in login list** on the ``local`` door, which is the everyday one;
* the **system-admin account** (ADR-0069 §5), which is a way in for the morning the
  identity provider is the thing that broke.

The first of those used to be added by the library, whenever a deployment had
registered no provider of its own. It is written here instead (ADR-0069 §3),
because *can anybody log into this instance* should be answerable by reading
one file rather than by working out what the library would have inferred from what
else was registered. An installation that registers nothing now starts, warns that
nobody can sign in, and lets nobody in.

**The registrations go before ``little_sister.app`` is imported**, which is the shape
every installation in this family uses: importing the app builds it and settles the
identity doors, and the server's start right after the import builds the engine from
the check configs (ADR-0091), so anything a deployment adds has to be there already.
``gunicorn`` serves ``wsgi:app`` (``instance.sh``), run from the repository root so
this module resolves on ``sys.path``, and loads ``little_sister.gunicorn_hooks``,
which is that start and the stop.

The system admin's password is a **reference, never a value**: ``setup.sh`` writes a
generated one into the git-ignored ``.env`` (ADR-0003), and what stands in the
committed line below is its address. A literal here would fail at startup rather than
quietly working, which is ADR-0023's rule doing its job in the one file where somebody
would be most tempted. If the variable is absent, the account's credential does not
resolve, that door is shut and the application keeps serving on the login list alone —
a fresh checkout that never ran ``setup.sh`` starts and says so on ``/system``.

No import fence is needed here, unlike a deployment whose registrations are all
plain imports: the calls below sit *between* the two imports, and an import sorter
does not move an import across a statement. That is also why the order is safe to
read as written rather than only safe to trust.
"""
from little_sister import identity, local_login

local_login.use_local()
identity.use_system_admin(reference="env://LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD")

from little_sister.app import app  # noqa: E402  (registrations precede the app)

__all__ = ["app"]
