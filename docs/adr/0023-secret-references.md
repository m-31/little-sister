# ADR-0023 — Secret references with deployment-registered resolvers

- **Status:** Accepted
- **Date:** 2026-08-23 (accepted 2026-07-18)
- **Related:** [ADR-0003 — Configuration & secrets via a `.env` file](0003-config-and-secrets-via-env-file.md)
  (extended here: the reference syntax and the `env://` scheme),
  [ADR-0001](0001-in-process-threaded-engine.md) ("no extra services" — unchanged for
  the core), [ADR-0015](0015-check-discovery-union.md) (config applies at startup, no
  live reload — the same stance governs secret rotation).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
[ADR-0003](0003-config-and-secrets-via-env-file.md) put all secrets in a git-ignored
`.env`, read through the process environment, and had a check reference a secret **by
its environment-variable name**; its closing note anticipated "a proper secret
manager" once a deployment grew. That point has come: a deployment wants its check
credentials (e.g. a GitHub token) in **AWS Secrets Manager**, another store — e.g.
**Parameter Store** — may serve other secrets, possibly both **in the same
deployment**, and a config-only deployment (one that carries YAML but no code) must be
able to say so.

Two constraints shape the answer. The core must not grow cloud dependencies or
services (ADR-0001's stance; a plain local install keeps needing nothing). And reads
from cloud secret stores **cost money per call** — re-reading a credential on every
check run (checks run every few minutes) would bill continuously for a value that
almost never changes.

## Decision
**The secret reference names its source, and the application registers the resolvers.**

1. **Reference syntax.** A secret-consuming config field takes a string reference,
   always shaped `scheme://address`:
   - **`env://GITHUB_TOKEN`** is an environment-variable lookup — ADR-0003's
     behavior, now named explicitly; `env` is built in.
   - any other **`scheme://address`** reference (`aws-sm://myteam/github-token`,
     `aws-ps://myteam/github/token`) is resolved by the resolver registered for its
     scheme. Different references may use different schemes — one deployment mixes
     stores per secret.

   Every reference carries a scheme: an environment variable is `env://GITHUB_TOKEN`,
   and `env` is a resolver `little_sister.secrets` registers for itself at import — so
   `resolve` has one path for every scheme instead of a special case plus a general
   rule. The reason is not symmetry but *safety*: with a bare name, a config field
   holding `ghp_16C7…` is a syntactically valid reference, so a pasted **credential**
   is looked up as if it were a name, fails, and echoes itself into the check's
   visible ERROR reason. Requiring the scheme makes that a malformed reference —
   caught by the grammar, exactly, with a message that deliberately does not quote
   what it rejected. (The alternative, guessing from the *shape* of a bare string,
   was tried and discarded: any rule tight enough to reject `ghp_…` also rejects
   legitimate names, and a rule loose enough to accept every legitimate name
   accepts most pasted secrets.)

   The **value never appears in config or version control** — only the address does
   (ADR-0003's principle, carried over).
2. **A resolver registry in the library, filled by the application.**
   `little_sister.secrets` exposes `resolve(reference)` and
   `register_resolver(scheme, resolver)` (a resolver: address → value, raising on
   failure). The library ships **only the env behavior**; a deployment registers its
   cloud resolvers **in its own code**, in the same import-before-`little_sister.app`
   slot its WSGI wrapper already uses to register check types — and owns their
   dependencies (boto3 never enters the core). Packaging resolvers as installable
   plugins later is an evolution of this, not a rewrite.
3. **Resolve once, at check instantiation.** A check resolves its references in its
   constructor and holds the values for the process lifetime; it **never touches a
   store during runs**. Rotating a secret therefore means restarting the process —
   consistent with how check configs already apply
   ([ADR-0015](0015-check-discovery-union.md): at startup, no live reload). An
   explicit, admin-triggered re-read may come later; nothing here precludes it.
4. **Failure semantics: config errors are loud, environment errors are visible.**
   - A **malformed reference** — an unknown scheme, no resolver registered for it —
     is a `CheckError` at load time, like any other config typo.
   - A **failed resolution** — store unreachable, secret absent — does **not** abort
     the engine: the check instantiates **pinned to ERROR**, its node carrying
     "secret unresolvable: …" as the reason, so the tree itself shows the problem
     while every other check keeps monitoring. It does not retry until restart
     (rule 3 holds even in failure).
5. **Scope.** This governs check (and later satellite) credentials. The application's
   own settings — `SECRET_KEY` and `LITTLE_SISTER_API_TOKENS` — may themselves be
   given as `scheme://address` references (`little_sister.secrets.resolve_setting`;
   the environment value already *is* the setting, so only the scheme shape is treated
   as a reference), resolved once at startup. `SECRET_KEY` additionally defaults to a
   **random per-start key** when unset, replacing the insecure development fallback
   (sessions reset on restart — no cross-worker skew under the single worker,
   ADR-0001). Failure keeps decision §4's split: a malformed reference still fails
   startup loudly; an unresolvable one degrades — random key / no API tokens — with a
   warning, so the dashboard stays up while a store is down.
6. **Config spelling.** A check's credentials are named in a `secrets:` block
   (`secrets: {token: env://GITHUB_TOKEN}`), parsed by
   `checks.base.parse_secret_refs`, and every name it declares is **required** — no
   default reference baked into the check type, since that is exactly what ties every
   instance of a type to one credential and prevents a deployment from running the
   same check type twice, once per team, with a token each.

## Consequences
- A deployment moves a secret to a store by changing **one reference string** and
  registering a resolver — `env://NAME` to `aws-sm://path`, nothing else moves.
- A credential pasted where its reference belongs cannot be mistaken for a name:
  it has no scheme, so it fails the load without being quoted back.
- The break is real but its blast radius was one deployment's two config files — no
  built-in check type takes a credential.
- A config-only deployment can name a store in YAML once a resolver for that scheme
  is registered (by a wrapper module today, an installed plugin later).
- Store reads happen a handful of times per process start — the cost profile of a
  restart, not of the check frequency.
- A wrong reference fails fast at startup; a broken store degrades to a **visible**
  per-check ERROR rather than an empty tree.
- The reference syntax and the registry become part of the library's public,
  version-promised surface once shipped.
- Tests substitute a fake resolver; the built-in env path is covered by the existing
  behavior's regression tests.

## Alternatives considered
- **One global secret provider, selected by config.** Rejected: a single deployment
  may legitimately need several stores at once, and a selection knob that can fall
  back silently (general config is deliberately lenient about problems) is exactly
  the wrong failure mode for security-relevant wiring.
- **A provider chain with a fallback order.** Rejected: implicit shadowing — *which*
  store answered? — where an explicit reference says it outright.
- **Resolve lazily / per run.** Rejected for cost: stores bill per read, and a
  per-frequency read pattern pays continuously for a static value.
- **No library involvement** (deployment checks call boto3 themselves). Works for a
  code-carrying deployment and remains possible, but leaves a config-only deployment
  unable to name a store, and every check type would invent its own spelling; the
  shared reference syntax is the small common piece that keeps them uniform.
- **Abort the engine on a failed resolution.** Rejected: one unreachable store would
  take down all monitoring and render an empty, unexplained tree; a pinned, reasoned
  ERROR keeps the failure inside the system's own language.
