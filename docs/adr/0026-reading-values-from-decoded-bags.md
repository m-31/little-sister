# ADR-0026 — Reading values from decoded bags (`values.py`)

- **Status:** Accepted
- **Date:** 2026-08-01
- **Related:** [ADR-0018](0018-markdown-rendering.md) (`plain` / `code` — the
  render-time escaping this ADR keeps *separate* from reading),
  [ADR-0023](0023-secret-references.md) (`secrets:` block — a config seam parsed the
  same way), [ADR-0015](0015-check-discovery-union.md) (checks load from YAML — where a
  `CheckError` from a read surfaces at load time),
  [ADR-0004](0004-status-aggregation-semantics.md) (any exception from `run()`
  becomes a visible ERROR — how a strict read surfaces at run time).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Both halves of the system read values out of **decoded bags** — nested
`dict`/`list`/scalar structures handed back by `yaml.safe_load` (a check's config
block, `config.yaml`, `nodes.yaml`, the maintenance side-table) or `json.loads` (an
API payload, in a deployment repo's own check types).

Every value in such a bag is typed `Any`. `Any` is assignable to anything, so
`mypy --strict` **cannot** flag a wrong-typed use at the point of use: in a deployment
check, `plain(payload["number"])` type-checked cleanly for as long as it existed and
then raised `AttributeError` the first time GitHub answered with an int rather than a
string. Tightening `plain`'s signature would not have caught it — the argument was
`Any` three frames earlier.

The codebase's answer up to now was a **convention**: stringify at every read,
`str(config.get("capture", "stdout"))`. It was applied at roughly fifty sites and held
almost everywhere, which is the problem — a rule enforced only by the author's memory
fails silently at the one site where it is forgotten, and the failure surfaces as a
broken check in production rather than a red gate.

A second, quieter cost: nested reads grew the `(bag.get("a") or {}).get("b")` idiom,
up to three `or {}` layers deep, which is unreadable *and* swallows the case where the
payload's shape genuinely changed.

## Decision
A top-level module, **`little_sister.values`**, holding five readers over a decoded
bag. Each takes the bag plus a `*path` of keys and **always returns the declared
type**:

```python
values.text(bag, *path, default="", required=False, where="") -> str
values.number(bag, *path, default=0, required=False, where="") -> int
values.real(bag, *path, default=0.0, required=False, where="") -> float
values.flag(bag, *path, default=False) -> bool
values.rows(bag, *path, where="") -> list[Any]
```

`*path` walks nested mappings, collapsing the `or {}` idiom to one call. Parameters
are typed `object`, not `Any` — the signature accepts anything while `--strict` keeps
checking the body.

**Failure policy**, chosen for a monitoring tool where a silently wrong *green* is the
worst possible outcome:

- **Absent** (missing key, a non-mapping on the way, or an explicit `null`) yields
  `default`. A cosmetic field the payload stopped sending must not take out the check.
- **`required=True`** turns absence into `CheckError` — for *structural* fields whose
  absence means the shape changed underneath us.
- **Present but uncoercible always raises**, never falls back. A `warn: "abc"` is a
  typo; defaulting it hides the mistake behind a plausible number. This matches
  `parse_duration`, which already raises on an unparseable duration.

`rows` is where `Any` legitimately leaves the module: its elements are bags in their
own right, read with these same functions.

**`CheckError` moves to a new `little_sister.errors`**, re-exported from
`checks.base` so existing imports keep working. `values` must be raisable from
`config.py` and `maintenance.py`, and importing `little_sister.checks` executes
`checks/__init__.py`, which registers every built-in check type as a side effect —
a dependency those layers have no business taking.

**Escaping stays at the render.** `values.text` returns the **raw** string;
`plain` ([ADR-0018](0018-markdown-rendering.md)) is applied at the moment of
formatting and never stored. An escaped value carries backslashes and can no longer be
put in a URL — a real defect found in a deployment check that had escaped an issue
number before interpolating it into a link.

## Alternatives considered
- **A typed dataclass per payload shape.** Rejected as the *general* answer: a
  dataclass's value scales with the number of places that consume it. A shape read in
  one ten-line loop gains indirection, not safety. Deployment repos still model what
  recurs (a repository record read by every aspect) — the two compose.
- **`TypedDict` + a `cast` at the boundary.** Real checking downstream, but a `cast`
  is an unchecked assertion: it moves the lie rather than removing it, and these
  payloads are partial and version-drifting.
- **`disallow_any_expr` on the parsing modules.** mypy supports it per-module and it
  would force narrowing everywhere. Rejected as too loud for the benefit.
- **Keeping the `str(...)` convention and tightening `plain`.** Rejected: it does not
  work. See *Context* — the argument is `Any` before it ever reaches `plain`.
- **Everything lenient.** Rejected: a schema change would read as "no alerts", the
  silently-wrong-green this policy exists to prevent.

## Consequences
- One place to fix a coercion bug, and `--strict` checks it.
- Internal callers converted in the same pass: `config.py`, `maintenance.py`,
  `checks/metadata.py`, `checks/command.py`, `checks/ssh/base.py`, and the threshold
  parsers in `checks/ssh/host_metrics.py`, `macos_memory.py`, `qnap_metrics.py` — the
  last three lose their `try/float(...)/except` blocks and gain a per-field error
  message (`thresholds.disk.warn: expected a number, got 'abc'`).
- Config validators that deliberately **warn and fall back** rather than raise —
  `config.py`'s `_valid_reason_cap` / `_valid_branch_cap` / `_valid_maintenance_cap` —
  are **left alone**: `load_config` degrades to defaults by design, which is a
  different policy from this ADR's and correct for that layer.
- `values` is public API on a versioned library. A deployment repo picks it up by
  re-locking against the library commit that introduces it.
