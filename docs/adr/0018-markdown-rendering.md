# ADR-0018 — Markdown rendering for node text

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-06-27)
- **Related:** [ADR-0012](0012-node-metadata.md) (`about`), [ADR-0013](0013-check-config-on-node.md)
  (check `config`), [ADR-0017](0017-node-title.md) (`title`) — the fields rendered
  here; [ADR-0007](0007-check-result-branches.md) (`CheckResult.reason`, where the
  helpers live); [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the
  envelope, which carries the raw Markdown); [ADR-0019](0019-inspection-popover.md)
  (the inspection card, which shows this rendered text);
  [ADR-0048](0048-an-assembled-content-security-policy.md) (the page's
  `Content-Security-Policy`);
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md) (a
  node's handbook, its details, the short link into the one and the status
  placeholders).
- **Register:** [`../decisions.md`](../decisions.md)

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
   Additionally, rendered links get **`rel="noopener noreferrer"`**, and **images are
   enabled for now**. Accepted tradeoff: an operator-authored `about` / `title` /
   `description` may embed a remote image, so the browser will fetch arbitrary image
   URLs (a privacy-beacon / mixed-content vector). Untrusted **reason** content is
   unaffected — the built-in capturing checks route it through `plain()` / `code()`,
   which escape `[` / `]` so an image can't form. Re-disabling is one line in
   `render.py`; a `Content-Security-Policy` would let images stay on with host limits.
   The images-off test is skipped while this holds. One runtime dependency (plus the
   tiny pure-Python `mdurl`); **no second sanitizer**.
3. **Reasons render like the rest, and the check author owns their safety.** The check
   base provides helpers to assemble a reason from untrusted / log content: **`plain(text)`**
   (escape Markdown specials so it renders literally) and **`code(text)`** (fence it as a
   code span / block). A check that captures external output wraps it with these. The
   **built-in capturing checks** — `command`, `ssh-command`, `ssh-script`, and the
   file / host error paths — use them, so their output is safe by construction.
4. **Inline vs block.** A field that is one line renders **inline** — a `title`, and a
   detail (decision 14) — with no block wrapper. `description`, `about` and each
   `reason` render as a **block** — a reason needs block rendering so `code()`-fenced,
   multi-line log output works — with tight CSS so a single-paragraph reason stays as
   compact as today.
5. **Where.** A node's page, the branch / leaf header (`title`), the inspection card
   ([ADR-0019](0019-inspection-popover.md)), and `reasons` wherever they appear (grid,
   detail, history, events). No `title=` tooltip carries a node's Markdown: the
   inspection card replaced them (ADR-0019 decision 4).

### Maintenance explanations
*(decided 2026-08-02; the rendered-field set grows, nothing above is withdrawn)*

An admin-authored **maintenance explanation** joins the rendered fields. It uses the
same block/inline filters and the same trust boundary; raw HTML is still escaped, and
the persisted/JSON value is still raw Markdown.

6. **The explanation is authored Markdown.** `MaintenanceEntry.reason` is rendered as
   a block on full read surfaces and inline on compact summaries, through the same
   filters and policy as the node fields. The editor always receives the untouched raw
   source; rendered DOM is never converted back into an input value. The literal
   `maintenance` sentinel remains the absence of an explanation and is not displayed.
7. **Compact means clamped HTML, not truncated source.** A banner or popover may clamp
   the rendered result with CSS, but must not shorten the Markdown string first: doing
   so can cut a link, code span or delimiter into invalid syntax. The full maintenance
   card, entry detail, conflict page and maintenance index keep the whole rendering.
8. **Persistence and JSON remain source contracts.** The file stores the same string in
   the same entry shape, and the envelope's `maintenance.note` carries it as raw
   Markdown for a client to render itself
   ([ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 4).

### Bare web URLs
*(decided 2026-08-02; link recognition grows, nothing above is withdrawn)*

Fully qualified bare `http://` and `https://` URLs are linkified through
markdown-it-py's own link rule. The scope is deliberately narrow: bare domains, email
addresses, FTP and protocol-relative text remain text, while the generated links pass
through the existing validation and hardening.

9. **An explicit web scheme is enough.** Plain `http://…` and `https://…` text becomes
   a link without requiring `<…>` or `[label](…)`. It produces the same `link_open`
   token as an authored Markdown link, so scheme validation, `target="_blank"` and
   `rel="noopener noreferrer"` remain one policy rather than a parallel HTML rewrite.
10. **Linkification is narrow.** Schemaless domains, bare email addresses, FTP URLs,
    protocol-relative URLs, code spans and text passed through `plain()` remain literal.
    This avoids turning hostnames and addresses in captured monitoring output into
    unintended navigation. The `linkify-it-py` parser is supplied by the declared
    `markdown-it-py[linkify]` runtime extra; no in-house URL recognizer or post-render
    HTML mutation is added.

### A node's handbook, its statuses, and one renderer for every text
*(decided 2026-10-24; the renderer learns the node it renders for and draws GitHub's
tables, nothing above is withdrawn)*

A node's `handbook` and its `details` join the rendered fields
([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)): a
detail is a line and renders inline, a handbook is a document and renders as a block.
Four rules join them, for every text the page shows.

11. **The renderer is handed the node it renders for.** The *About* card, a line, the
    inspection card and the handbook's own page each render a node's text for that
    node, so that what the text names relative to its node resolves against it.
12. **`handbook` and `handbook#<section>` lead into the node's handbook.** A link
    written so leads to the handbook of the node the text belongs to — for a detail
    given down, the node it is given on — `/handbook/<path>#<section>`, rewritten in
    the `link_open` rule where every link's target is set (decisions 2 and 9). A
    handbook's headings are anchored as GitHub anchors them: `## Sign in` is
    `#sign-in`, a second heading of the same words `#sign-in-1`; and a link to a
    section of the page itself, `#sign-in`, stays in the page, where every other link
    opens a tab of its own — the short form's among them, but on the handbook's own
    page, where it is a section of the page itself. In a text that belongs to no node —
    a note on the links page, a reading's sentences, whose row does not say the node —
    it leads nowhere: its words stand, and no link.
13. **`{ok}`, `{warn}`, `{error}`, `{maintenance}` and `{undefined}` are drawn as the
    status's sign**, in either case: its cue and its word on its own tint, in every text
    the page shows — an about, a description, a detail, a handbook, a title, a line, a
    maintenance note. A line's own braces are its template's
    ([ADR-0126](0126-a-line-is-a-template-over-its-record.md)) and are filled before
    the line is rendered, so what is left of one in the line is the text's. One in a
    code span or escaped is text, and `plain()` (decision 3) escapes a placeholder's
    brace and no other, so that captured text stays the text it was. Where a text leaves
    the instance — the Copy document, which carries lines, notes, titles and what a run
    found and ran with, and `little-sister-jira`'s draft — one function of the library
    writes the short form out to its full address, and a status as the Copy document
    writes one, *error ⛔*.
14. **One renderer renders every text, GitHub's tables and strikethrough among it.** A
    node's about, description, title, handbook and details, a line, a maintenance note,
    what a check ran with and what its run found are rendered by one configuration —
    CommonMark with GitHub's tables and strikethrough, markdown-it-py's own rules, and
    decision 13's signs — so that whoever writes a text never asks where it will stand.
    A text renders as a block where it is read whole, and inline where it stands on one
    line — a title, a detail, and a line or a note a page sums up in a row (decisions 4
    and 6) — where a table, like a list, stays its text. A table wider than what holds
    it scrolls sideways inside itself, its words whole in their cells, in a card, a line
    and a phone's page alike. `plain()` escapes each tilde of a run of two or more, so
    that captured text cannot strike itself through, and leaves a lone one — a home
    directory's `~/` — clean; a table needs a delimiter row of a line of its own, which
    a one-line text cannot hold and multi-line output does not reach through `code()`,
    so a pipe stays as it is, as the block markers do. A handbook's own page alone
    anchors its headings (decision 12): an anchor changes nothing a reader sees, and
    every heading of every text anchored would give one anchor twice where two texts on
    a page share a heading.

## Consequences
- One new runtime dependency, safe by default, so we don't own a security-sensitive
  renderer ourselves.
- Consistent rich text (links, emphasis, `code`, lists) across the UI; the raw Markdown
  still reads acceptably if rendering is ever bypassed.
- **Reason safety is explicit and local.** A check folds external bytes in via
  `plain` / `code`, so the danger is handled where the bytes enter, not papered over
  globally; our built-ins do this, and a custom check that forgets is the author's
  responsibility (operator-controlled — ADR-0007).
- **No extra sanitizer.** The posture is the safe renderer and `rel=noopener`, images
  on. The page's `Content-Security-Policy` is assembled and ships Report-Only
  ([ADR-0048](0048-an-assembled-content-security-policy.md)); enforcing it is a step of
  its own.
- The JSON envelope ([ADR-0080](0080-the-envelope-is-the-snapshot-published.md))
  carries the raw Markdown strings, the short form and the status placeholders among
  them, which its contract defines; a client renders its own.

## Alternatives considered
- **Keep `reasons` as escaped plain text** (don't render the captured field). Safest and
  simplest, but loses the links / emphasis a check may intend; rejected in favor of
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
