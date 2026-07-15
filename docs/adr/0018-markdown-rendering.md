# ADR-0018 — Markdown rendering for node text

- **Status:** Accepted
- **Date:** 2026-06-26
- **Related:** [ADR-0012](0012-node-metadata.md) (`about`), [ADR-0013](0013-check-config-on-node.md)
  (check `config`), [ADR-0017](0017-node-title.md) (`title`) — the fields rendered
  here; [ADR-0007](0007-check-result-branches.md) (`CheckResult.reason`, where the
  helpers live); [ADR-0008](0008-json-output-api.md) (JSON envelope carries the raw
  Markdown, unchanged). A later ADR-0019 (inspection popover) will display much of
  this rendered text.
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-06-26):** image rendering — initially **disabled** here as a safety
> measure (no remote `![]()` beacons or mixed content) — has been **enabled for now**.
> Accepted tradeoff: an operator-authored `about` / `title` / `description` may embed a
> remote image, so the browser will fetch arbitrary image URLs (a privacy-beacon /
> mixed-content vector). Untrusted **reason** content is unaffected — the built-in
> capturing checks route it through `plain()` / `code()`, which escape `[` / `]` so an
> image can't form. Re-disabling is one line in `render.py`; a `Content-Security-Policy`
> would let images stay on with host limits. The images-off test is
> skipped while this holds.

## Context
Several node fields are **Markdown** but shown as **plain text** today: `title`
(ADR-0017), `about` (ADR-0012), a leaf's `description`, and each `reason`. The runtime
dependencies are deliberately small (Flask + gunicorn + PyYAML + tzdata), so a renderer
is a dependency decision.

`reasons` differs from the others. The operator-authored fields are static text; a
reason is **check-authored and often assembled from captured output** — command
stdout/stderr, an ssh/http response, a log line. The check author is responsible for
what their check emits, but they need **tools to fold genuinely external bytes into a
reason safely**, so a stray `*` — or a `<script>` — in that output is inert rather than
mis-rendered or injected.

## Decision
Render Markdown **server-side**, via a small **safe-by-default** library behind Jinja
filters; render **all four fields**, and give checks helpers to keep reason content safe.

1. **Server-side Jinja filters** — `markdown` (block) and `markdown_inline` (one line,
   no wrapping `<p>`). Fits the server-rendered app and the fragment polling, which
   already swaps in server HTML; nothing moves to the client.
2. **markdown-it-py, safe defaults.** Raw HTML is **escaped**, and link schemes are
   validated (`javascript:` / `vbscript:` / `file:` / unsafe `data:` dropped).
   Additionally, rendered links get **`rel="noopener noreferrer"`**, and **images were
   disabled** (no remote `![]()` beacons or mixed content) — since **enabled**, see the
   Update note above. One runtime dependency (plus the tiny pure-Python `mdurl`); **no
   second sanitizer**.
3. **Reasons render like the rest, and the check author owns their safety.** The check
   base provides helpers to assemble a reason from untrusted / log content: **`plain(text)`**
   (escape Markdown specials so it renders literally) and **`code(text)`** (fence it as a
   code span / block). A check that captures external output wraps it with these. The
   **built-in capturing checks** — `command`, `ssh-command`, `ssh-script`, and the
   file / host error paths — use them, so their output is safe by construction.
4. **Inline vs block.** `title` and `description` render **inline** (one-line labels,
   no block wrapper). `about` and each `reason` render as a **block** — a reason needs
   block rendering so `code()`-fenced, multi-line log output works — with tight CSS so a
   single-paragraph reason stays as compact as today.
5. **Where.** The detail page, the branch / leaf header (`title`), and `reasons`
   wherever they appear (grid, detail, history, events). Card hover content moves to the
   inspection popover (a later ADR-0019). The native `title=` tooltips keep the raw
   Markdown for now.

## Consequences
- One new runtime dependency, safe by default, so we don't own a security-sensitive
  renderer ourselves.
- Consistent rich text (links, emphasis, `code`, lists) across the UI; the raw Markdown
  still reads acceptably if rendering is ever bypassed.
- **Reason safety is explicit and local.** A check folds external bytes in via
  `plain` / `code`, so the danger is handled where the bytes enter, not papered over
  globally; our built-ins do this, and a custom check that forgets is the author's
  responsibility (operator-controlled — ADR-0007).
- **No CSP and no extra sanitizer this slice.** The chosen posture is the safe renderer
  + `rel=noopener` (images were off, now on — see the Update note). A
  `Content-Security-Policy` stays a worthwhile separate
  hardening step (it needs the inline poll script and the filter form's `onchange`
  handlers externalized / nonced, and the CDN allowlisted) but is not part of this ADR.
- The JSON envelope ([ADR-0008](0008-json-output-api.md)) is **unchanged**: it carries
  the raw Markdown strings; a client renders its own.

## Alternatives considered
- **Keep `reasons` as escaped plain text** (don't render the captured field). Safest and
  simplest, but loses the links / emphasis a check may intend; rejected in favour of
  rendering **plus** per-reason helpers that put the choice in the check author's hands.
- **A typed reason carrying a `markdown` / `plain` flag.** Cleaner in theory, but reasons
  are `list[str]` through `CheckResult`, `Status`, the event log, history, and the JSON
  envelope — a wide, invasive change. The `plain()` / `code()` helpers achieve the same
  safety while keeping reasons plain strings.
- **A no-dep, in-house micro-renderer** (escape-first + a few regexes). Zero new deps and
  fits the minimal-deps ethos, but we'd own a security-sensitive component and forgo
  CommonMark; rejected.
- **Python-Markdown or mistune + a sanitizer.** Both pass raw HTML through by default, so
  they need a second (compiled) dependency (`bleach` / `nh3`); markdown-it-py's safe
  defaults are a better fit. **mistune** (zero transitive deps) stays the fallback if the
  `mdurl` dependency is unwanted, at the cost of explicit escaping.
- **Client-side rendering** (`marked` + `DOMPurify` via CDN). Moves rendering to JS, must
  re-run after every poll, and skips the non-JS / JSON paths; rejected.
