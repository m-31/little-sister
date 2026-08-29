# ADR-0070 — The report on unclaimed configuration files runs at the end of registration

- **Status:** Accepted
- **Date:** 2026-08-29
- **Related:** [ADR-0031](0031-deployment-config-directory.md) (the aspect vocabulary
  and the unknown-candidate warning this moves),
  [ADR-0035](0035-registering-a-config-aspect.md) (the registration whose ordering rule
  this makes followable),
  [ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md)
  (`announce_doors()` — the precedent in exactly this position)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

ADR-0031 §3 made an unrecognized candidate in a configuration root **warn and be
ignored**, so that a `config/node.yaml` sitting there doing nothing is visible rather
than silent. ADR-0035 then let a dependent package register an aspect of its own, and
its §5 answered the obvious ordering question by telling packages to **register before
the app is imported**, on the stated ground that "the unknown-candidate warning fires
once per root at the first resolution, so a registration arriving after it has nothing
left to prevent".

The rule is right. It is also not sufficient: a deployment that follows it exactly is
still told, at every start, that its own configuration file is not a known aspect — a
file that was read correctly and is working.

**The registering call is itself the first resolution.** That is not one package
behaving unusually; it is the pattern this family settled on, and the library follows
it too. Every registrar declares its aspect and then reads it immediately, so that a
broken configuration file fails at startup rather than at the first click: the built-in
login list is declared and then loaded by `local_login.use_local()`, and each dependent
package that registers an aspect loads it in the same breath. Every one of those reads
resolves the configuration roots — and resolving a root was what scanned it. So
whichever registration happened to run first performed the scan, and **every aspect
registered after it was named as unknown for the life of the process**.

That makes the sequence **unfollowable rather than delicate**. A deployment cannot
satisfy "register before the app is imported" by ordering its imports, because it would
have to know which of its imports reads a root and place its own registrations above
that one — and no ordering at all helps the package that is genuinely first. It is
import order deciding an observable, which ADR-0035 §4 already refuses for aspect
*shapes*: *import order cannot silently redefine a shape.*

**Making the plugins read lazily is the obvious first move and it fixes nothing.** It
would remove the trigger that exposed this while leaving the mechanism intact — several
registrars read eagerly in the same window, one of them this library's own — so the
scan would simply be performed by whichever of them ran first. It would also trade away
the property the eager read exists for: that a broken configuration file is known at
startup. The declare-then-read shape is correct. The complaint is attached to the wrong
moment.

## Decision

**The scan stays where it is and stays silent; the complaint moves to the end of the
registration window.**

1. **Resolving a configuration root says nothing.** `config_roots()` no longer scans,
   so no read — nobody's registration, no loader, no tool — can spend or misdate the
   report. The once-per-root cache goes with it, and so does `forget_scanned_roots()`:
   with the scan no longer riding a function called on every aspect lookup, there is
   nothing left to remember and nothing for a test to forget.

2. **`config_dir.announce_aspects()` is the report**, called once from
   `little_sister.app` at import. That is the same position, and the same argument, as
   `announce_doors()` (ADR-0069): everything registers **before** the app is imported,
   so that import is the moment at which the set of aspects is final and a leftover
   file is genuinely leftover.

3. **Anything may call it.** It is a public function taking the same path-list
   argument every other entry point here takes, not an application-private step. A
   tool that reads one aspect and never builds an app gets the same report from the
   same line if it wants it; a process that has no final moment simply does not ask,
   and gets silence — which is the honest answer where *unclaimed* is not yet defined.

4. **It covers every configured root**, not only the roots something has happened to
   resolve. This is a change in what gets said, not only in when: a stray file in a
   site root that nothing had reason to open was previously never looked at.

5. **The message names the known aspects with the packages that registered them** —
   `config/identiy.yaml is not a known configuration aspect and is ignored (known:
   actions, checks, csp, identity (acme_sso), links, nodes, settings, users)`, with the
   library's own aspects printed bare. That attribution is available only late, and it
   is most of the value of moving the report: a near-miss spelling now points at the
   aspect it missed, and at the package whose document the operator meant to be
   editing.

6. **Nothing else changes, ADR-0035 §5 included.** An unrecognized candidate is still
   ignored and never stops the monitor; a non-candidate — a `README.md`, a dotfile, an
   editor's `.bak` — still passes in silence. And a package still registers before the
   app is imported. What changes is *why*: the reason is the **read**, not the warning.
   `aspect_in` looks the name up in `ASPECTS`, so a package that resolves its own file
   before declaring it gets a `KeyError` rather than a diagnosis, and the application
   resolves its configuration during its own import. The rule was never wrong; it was
   resting on a mechanism that could not deliver it.

## Consequences

- A deployment that registers an aspect of its own is no longer told at every start
  that its own configuration file is unrecognized, and a genuine stray file still is —
  so the warning keeps the meaning ADR-0031 §3 added it for.
- **The report is emitted in one place**, which is a property worth having on its own:
  previously the warning's timing, and therefore its content, depended on which import
  in somebody else's deployment read a root first.
- A process that imports `config_dir` without importing the app now gets **no** report
  unless it asks for one. That is deliberate (point 3), and it is a real loss for
  anything that relied on the resolution to complain on its behalf; the fix is one
  line, in the caller that knows when its own registrations are finished.
- `forget_scanned_roots()` is gone from the public surface. It existed only to undo a
  cache that no longer exists.

## Alternatives considered

- **Re-scan every root each time an aspect is registered.** Correct at the end, and
  noisy in the middle: each registration would re-report every file not yet claimed by
  a *later* one, so a deployment with three plugins would read its own configuration
  tree described wrongly twice before being described rightly once.
- **Keep the scan at the first resolution, and suppress a warning retroactively when
  the name is registered later.** It cannot be done: the line is already in the log,
  and a monitoring application that edits its own log to hide a complaint it should
  not have made has a worse problem than the complaint.
- **Make the report application-private** — a step inside the app import, callable by
  nobody. One less public name, at the cost of the only mechanism a tool has for the
  same question, and for no benefit: the report reads state and changes nothing.
- **Drop the unknown-candidate warning entirely.** One line, and it loses the check
  that catches `config/node.yaml` (singular) sitting there doing nothing — the exact
  failure ADR-0031 §3 added the warning for, and the one this record exists to keep
  trustworthy.
- **Let each package read its aspect lazily**, so that no registration performs a
  resolution. Discussed in the context above: it removes the trigger, not the
  mechanism, and it costs the startup failure the eager read is for.
