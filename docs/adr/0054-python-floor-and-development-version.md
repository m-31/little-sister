# ADR-0054 — A supported floor of 3.11, developed on 3.14

- **Status:** Accepted
- **Date:** 2026-08-09 (restating decisions taken 2026-06-27)
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (single-host threaded
  engine — the reason free-threading is interesting at all),
  [ADR-0002](0002-rlock-snapshot-synchronization.md) (locking is GIL-independent, so
  nothing in this record's reasoning is load-bearing for correctness),
  [ADR-0022](0022-generated-release-branch.md) (what a release is; the gate this adds
  two commands to runs inside it)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

**On 2026-06-27** `requires-python` sat at `>=3.14` with no
recorded rationale, and the question was whether to keep it or loosen it. The code
forced nothing that new then and forces nothing that new now, so the pin was a
**choice, not a constraint** — and the runtime context made a high floor cheap: the
deployment is a single host we control ([ADR-0001](0001-in-process-threaded-engine.md)),
installed and run with **uv**, which manages the interpreter per environment rather than
taking whatever a distribution ships.

**What changed: the library is being published.** That context described the only
consumer that existed — a host whose interpreter we provision. On a package index the
consumer is a stranger whose interpreter we do not choose, and the common server
distributions sit at 3.11 to 3.13 while nothing ships 3.14 yet. `>=3.14` therefore reads
to almost every interested reader as *"Requires-Python >=3.14; the candidate selected …
does not match"* — which looks like a broken package rather than a deliberate floor,
and which no line of code asks for. The answer of 2026-06-27 anticipated being
revisited if an interpreter-version constraint appeared; the constraint turned out to
be reach rather than a stuck host.

**The floor was measured, not estimated** — each interpreter fetched, the package
installed, the suite run:

- **3.9** is impossible: `markdown-it-py[linkify]>=4.2.0` needs ≥3.10, so resolution
  refuses before any code runs.
- **3.10** fails on `typing.Self` (`status.py`), `datetime.UTC` (`api.py`, `app.py`) and
  `Traversable.joinpath`, which is variadic only from 3.11 (three places in `slots.py`).
- **3.11** is the floor. Every module imports and the whole suite passes.
- Syntax is not the constraint at all: `compileall` is clean even on 3.9, because every
  module carries `from __future__ import annotations` and there is no `match` and no
  PEP 695.

One finding shaped decision 3. The suite initially failed on 3.11–3.13 in a single file,
where a class annotated a method with its own name — legal to a type checker, and a
`NameError` at import on anything that does not evaluate annotations lazily (PEP
649/749). No type checker can catch that, and `datetime.UTC` had arrived since 2026-06-27
without anyone noticing. **A floor nobody exercises is a claim, not a promise, and it
decays silently.**

## Decision

1. **`requires-python = ">=3.11"`** — the measured floor, and the widest promise the
   code can keep without a port.

2. **Development, the pinned interpreter and the everyday gate stay on 3.14**
   (decided 2026-06-27). `.python-version` pins the exact patch level,
   so every environment that runs the suite runs it on the same interpreter, and uv
   downloads it rather than adapting to whatever is present. The floor is what we
   *support*; 3.14 is what we *use*.

3. **The floor is checked, in the two ways it can break** — this is what makes
   decision 1 a promise rather than a claim, and it is the part a floor of 3.14 had no
   need for:
   - `mypy --python-version 3.11` on **every commit** (the pre-commit hook). Static,
     about a second, and it names exactly the class that broke 3.10: a stdlib name or
     signature the floor does not have.
   - The **full suite on 3.11**, once per release, in the quality gate the release
     runs. It catches what no type checker can — a runtime semantic such as the
     lazily-evaluated annotation above. It runs
     `--isolated`, so it never touches the pinned environment, and it takes its
     dependencies from the `dev` group rather than a list of its own, because a second
     dependency list is one that eventually disagrees with the first.
   - `ruff`'s `target-version` is the **floor**, not the development version: the `UP`
     rules propose modern idioms, and one the floor cannot run is a proposal to break
     decision 1.

4. **The free-threading door stays open** (decided 2026-06-27). A floor
   forbids *requiring* 3.14, not running on it, and correctness never depended on it —
   [ADR-0002](0002-rlock-snapshot-synchronization.md) locks explicitly regardless of the
   GIL.

5. **No compatibility shims.** The floor is what the code is written against, not
   something it adapts to at runtime: no `sys.version_info` branches, no
   `typing_extensions`, no backport imports. A floor of 3.14 bought that simplicity by
   having one version; this record buys it by having one *target*, with the checks in
   decision 3 keeping the two honest. If a shim ever looks necessary, that is the moment to raise
   the floor instead — in a superseding record.

## Consequences

- **`v0.3.0` is not the first published version.** It is tagged and pushed on the forge
  and it declares `>=3.14`, and `requires-python` is frozen per artifact — so the
  relaxation necessarily ships as a new version, and publishing 0.3.0 first would open a
  window in which every `pip install` fails for no gain. The three plugins declare
  `little-sister>=0.3.0`, a floor rather than a pin, which the next version satisfies.
- **The floor is stated twice and has to agree with itself.** `requires-python` is what
  a resolver honors; the `Programming Language :: Python :: 3.x` classifiers are what
  somebody filtering the index reads. Lowering one and not the other hides the package
  from exactly the people the change was for, and it happened the moment the floor moved.
  The classifiers must therefore **start at the floor** and be contiguous from it —
  enforced by the release check rather than remembered, because there is no reason a
  human should be the link between two lines of the same file. They need not reach the
  newest Python: claiming a version nobody tested would be the worse defect.
- **The pin does not ship, and that had to be arranged.** `.python-version` names the
  interpreter *development* uses; on the public release branch it would contradict
  `requires-python` from two lines away — somebody cloning the release to run it on a
  supported 3.12 would get uv insisting on 3.14.6, or an older uv failing outright. It
  never reached the wheel or the sdist, only the branch, and keeping it off the branch
  needed a mechanism that did not exist: the release's doc lists classify Markdown and
  nothing else, so a non-document could not be dropped at all. Hence `drop_files`, which
  is general — the next dev-only dotfile runs into the same gap.
- **What is given up:** PEP 695 generics, the `type` statement, `itertools.batched`, and
  lazily-evaluated annotations — the modernizations a floor of 3.14 had left available
  for later. Decision 3's checks are what turn each of them from a silent trap
  into a failed gate.
- **The plugins carry their own `requires-python`** and have to follow, each with its own
  version, or somebody on 3.12 can install the library and not the plugin.
- **Everyday cost:** one extra second on each commit, and about half a minute on each
  release.
- **No external contract is affected** (decided 2026-06-27): federation
  peers and the client apps speak JSON over HTTP, so the runtime version is invisible to
  them.
- **A consumer-facing change**, so it belongs in the CHANGELOG rather than only here: a
  widened floor is the kind of thing somebody chose this library *for*.

## Alternatives considered

- **Keep `>=3.14`** — the answer of 2026-06-27, and correct for its context: one
  version to lint, type-check and test against, on a host whose interpreter we
  provision. It stops being correct at the moment the audience is people whose
  interpreter we do not choose.
- **Relax later, in some version after the first upload.** Sound on the mechanics —
  `requires-python` is per artifact, so the decision is revisitable at every version —
  and it loses on the thing that is not mechanical: the compatibility is free *today*
  because it was measured today, and one PEP 695 generic turns the later relaxation from
  a metadata edit into a port, silently, while somebody writes ordinary code.
- **`>=3.12`.** One fewer version to keep working, and it gives up the distributions
  sitting at 3.11 — the widest part of the installed base — for nothing the code wants.
- **`>=3.10` or lower.** Measured impossible without a port: see the context.
- **Declare `>=3.11` and keep testing only on 3.14.** This is the option that looks
  free and is not. It is the state the 3.14 floor left behind, where `datetime.UTC`
  walked in unnoticed; the difference now is that the promise would be public.
