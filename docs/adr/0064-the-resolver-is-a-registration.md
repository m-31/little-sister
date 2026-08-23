# ADR-0064 — A secret resolver is a registration like the others

- **Status:** Accepted
- **Date:** 2026-08-22
- **Related:** [ADR-0023](0023-secret-references.md) (the reference grammar and the
  registry this makes first class), [ADR-0051](0051-what-startup-refuses.md) (the
  duplicate-claim refusal this copies, and the `/system` origin card),
  [ADR-0035](0035-registering-a-config-aspect.md) /
  [ADR-0034](0034-template-slots-for-dependent-packages.md) /
  [ADR-0037](0037-extension-static-assets.md) (the neighboring seams, and the
  warn-and-skip rule that does **not** apply here),
  [ADR-0003](0003-config-and-secrets-via-env-file.md) (the `env` scheme's behavior)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Five kinds of contribution reach a running instance from a package installed beside
the library: a check type, a template slot filler, an asset, a configuration aspect,
and a **secret resolver**. Four of them are registrations in the full sense — the
registry records who made the claim, `/system` prints it, and a collision has a
stated outcome. The fifth was a bare dictionary assignment:

```python
_resolvers[scheme] = resolver          # last writer wins, silently
```

Three asymmetries follow from that one line. It **records no registering package**,
so nothing can say which installation answers for `aws-sm://`. It is therefore
**absent from `/system`**, the page whose whole job is to say what is installed and
what it contributed — a seam nobody can see from the running instance is
indistinguishable from one that silently did not take. And a second registration of
a scheme **replaces the first with no sound**, where a second claim on a `type:`
name refuses at startup naming both projects (ADR-0051).

That asymmetry was invisible while only a *deployment* registered resolvers. A
deployment registers its own, in one place, in code it owns; and a deployment that
deliberately overrides the built-in `env` resolver with an implementation of its own
is **using a feature** ADR-0023 offers it, not tripping over a hole. Overriding is
about the *registry* — the schemes themselves are additive, `aws-sm://` and whatever
provider comes next sitting beside `env://`, mixed per credential, no store
superseding another.

It stops being invisible the moment a **package** claims a scheme, because a scheme
is *where a credential is read from*, and import order would be deciding it. Two
installed packages claiming `aws-sm://` means one package's checks authenticate
against the other's store, with the other's client, under credentials nobody chose:
either a load of `SecretError`s on a machine nobody is watching, or — worse, and
perfectly quiet — a secret that does resolve, from the wrong place.

This is not hypothetical for long. `little-sister-aws` already carries the AWS
resolvers, and it carries them behind an explicit `register_aws_secret_resolvers()`
call a deployment must make **precisely because this record did not exist**: a
package cannot be allowed to claim a scheme on import while the registry cannot say
who claimed what. Making this seam first class is the prerequisite for a package
registering a resolver on import, or through discovery.

## Decision

1. **A registration records the package that made it**, inferred from the call site
   through `origins.calling_package()` — the same inference `register_aspect` uses,
   for the same reason: the one-line call site inside a package already says who it
   is, and a name the caller had to repeat is a name the caller can get wrong. A
   caller that cannot be identified (`__main__`, which is what *any* script is
   called when run directly and so names no installation) records nothing and is
   named as unidentified where it must be printed.

2. **The resolver travels with its provenance**, in one `Registration` record per
   scheme, rather than beside it in a second table. A parallel dict of owners is a
   dict that can disagree with the registry it describes, and it is one more thing
   for a test to substitute.

3. **A scheme is claimed once, and a second claim from a different package refuses
   at startup**, naming both packages and the scheme. This is the ADR-0051 rule and
   the ADR-0051 reasoning: these refusals are hard where the neighboring seams warn
   and skip, because a missing button costs a page one control while a monitoring
   system that reports confidently *without measuring what the operator believes it
   measures* is worse than one that is down. Re-registering from the **same**
   package replaces silently — a registration module may be imported more than
   once, and refusing that would refuse a reloading server.

4. **Replacing another package's scheme stays available, and is said out loud** —
   `register_resolver(scheme, resolver, replace=True)`. ADR-0023's promise that a
   deployment may substitute its own `env` implementation is kept in full; what it
   no longer does is happen by accident. The keyword is the whole discriminator: a
   deployment is not structurally distinguishable from a package — `little_sister_stress`
   is an ordinary installed package that happens to be a deployment — so any rule
   that tried to infer *"the deployment wins"* would be a heuristic that refuses the
   exact case it exists to allow.

5. **What was replaced is remembered and shown.** A replacement is the one fact on
   this seam that cannot be deduced from the outcome: the page would otherwise show
   a scheme owned by whoever owns it, with nothing to say that somebody else used
   to. Re-registering from the replacing package carries it forward, so a reload
   does not quietly un-say the override.

6. **`/system` prints the seam twice, on purpose.** Each package's inventory row
   gains `secret <scheme>://` beside its types, slots, assets and aspects — that
   card answers *what did this installation contribute*. And the extensions card
   gains the **whole scheme list** with each scheme's owner, built-in `env`
   included, which the aspects line beside it deliberately does not do for the
   library's own aspects. The schemes are additive and a reference names exactly
   one, so the full list is the only answer to *what may I write in this config
   field* — and leaving the library's own claim out would make an **override** of it
   look like an ordinary first registration.

   **It is a table, shaped like the slot table above it** — `Scheme`, `Package`,
   `Replaces`, `From` — and not the prose line the aspects use. The two seams
   differ in how many entries a real deployment has: one or two aspects is a
   sentence, while a deployment with named identities carries seven or more schemes
   (two per identity plus the ambient pair and `env`), which as a comma list wraps
   into a paragraph the eye has to re-find the boundary in on every item. `From`
   means in this table exactly what it means in that one, so the columns are
   learned once. `Replaces` is empty in every ordinary deployment and is a column
   anyway, because it is the one fact here the outcome cannot show.

## Consequences

- **The extensions card grows a table every deployment sees.** This seam always has
  an entry — the library claims `env` itself — so unlike the slot and aspect
  entries beside it, the scheme table is never absent. That costs a deployment with
  no extensions a one-row table it did not ask for, and buys the two questions only
  the whole list answers. It does not change *whether* the card is drawn: the
  library registers its own slot fillers unconditionally, so the card was already
  always there.
- **A deployment that overrides `env` must now say `replace=True`.** That is a
  breaking change for exactly that deployment, and a one-word one; every other
  registration is untouched. No plugin in the family overrides anything.
- **`little_sister.secrets` is not on the check-authoring surface**, so the epoch
  does not move (ADR-0051 §2 and its snapshot). The surface a *plugin* is versioned
  against is `architecture.md` §11's fenced block, and this module has never been in
  it. The behavior change is a release note, not an epoch.
- **A package may now be trusted to register a resolver on import**, which is what
  this record exists to unblock. It does not do so yet: `little-sister-aws` keeps
  its explicit call, because which store a deployment reads its credentials from is
  a decision and a decision should be readable at the place it is taken.
- **`SchemeConflictError` is a new exception in `little_sister.secrets`**, not
  `CheckError` — the check base imports this module, so this module cannot import
  the check base. The refusal raises out of the application's import-before-app
  block, which is where a deployment can read it.
- **Two packages that both want `aws-sm://` cannot be installed together**, the same
  honest outcome bare `type:` names have, with the same workaround available to
  whoever hits it: rename the scheme in one of them.

## Alternatives considered

- **Leave it last-wins and document it.** Cheapest, and it is what stands today. It
  survives only as long as no package claims a scheme, and the failure it permits is
  the silent one — a check reading a credential from a store nobody chose. The
  registry cannot even report it after the fact, because it does not know who
  registered what.
- **Warn and skip, like the slot and aspect seams.** Consistent with the neighbors
  and wrong for the same reason first-registration-wins was wrong for `type:` names
  (ADR-0051): the loser's checks would silently read the winner's store, and a
  warning in a log is not where an operator learns that.
- **Infer the deployment and let it always win.** No new keyword, and it reads well
  in the abstract — until one asks how a deployment is recognized. By the absence of
  installed metadata? `little_sister_stress` is a proper installed package. By being
  the module that imports `little_sister.app`? A package's registration function is
  called from exactly there too. Every discriminator is a guess about somebody's
  packaging, and a wrong guess refuses the override this is meant to preserve.
- **Namespace the schemes by package** (`little_sister_aws:aws-sm://`). Collisions
  become impossible and every reference says which package answers — at the cost of
  rewriting every credential line in every deployment, for a collision that may
  never happen. Same trade ADR-0051 declined for type names, with the same answer: a
  refusal costs nothing until the day it fires, and on that day it says more than a
  prefix would have.
- **Let the resolver declare its own package as an argument.** Explicit, and one
  more thing to get wrong — a copied registration line carrying the package name it
  was copied from would attribute a scheme to an installation that does not have it,
  which is worse than not saying.
