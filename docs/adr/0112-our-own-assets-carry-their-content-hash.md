# ADR-0112 — Our own stylesheet and scripts carry their content hash, and an open page notices when they moved

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0037](0037-extension-static-assets.md) (decision 6, the form this
  takes: a registered package's asset is addressed by eight hex digits of its
  SHA-256 and kept for good), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (the refresh, which swaps a part of the document and fetches nothing else),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (decision 7: the refresh
  waits while a pin's editor is open), [ADR-0029](0029-per-user-presentation-preferences.md)
  (the kiosk, which nobody reloads), [ADR-0048](0048-an-assembled-content-security-policy.md)
  (untouched: the files stay on our own origin)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A page linked `/static/css/overview.css` and its scripts by their bare names. Two
things followed, and they are not the same thing.

A browser that loads a page afresh may be handed yesterday's file under today's URL:
nothing in the name says the content changed, so what it shows after an upgrade is
its cache's to decide. A stylesheet fix was on disk, correct, and not on the screen.

And a page that is **open** keeps the files it was loaded with whatever their URLs
are. The refresh fetches the page's own address with `fragment=1` and swaps the
answer into the document; it fetches no stylesheet and no script. After an upgrade
such a page runs the old `poll.js` against markup written for the new one, until
somebody reloads it — and a wall display has nobody. The stale script is the worse
half, because the script and the markup it swaps have to agree.

A registered package's assets never had the first problem: their URL carries a hash
of their content ([ADR-0037](0037-extension-static-assets.md)). Ours were the
stragglers. Nothing had the answer to the second.

## Decision

### 1. A URL for one of our stylesheets or scripts carries the file's hash

`/static/css/overview.css?v=1a2b3c4d`: the first eight hex digits of the file's
SHA-256, as a registered package's asset has them. The hash is added where a URL is
**built** — every `url_for('static', …)` for a `.css` or a `.js` file gets it — and
not by a helper a template has to remember, so no page can link one without. A
template writes no such URL by hand.

### 2. Only stylesheets and scripts

They are what a page and the markup it is sent have to agree on. The tab icons, the
web manifest and the avatars keep their plain names: they change rarely, and a
bookmark, a pinned tab and the manifest ask for them by name from outside any
template.

### 3. A hashed URL is kept for good; any other is not

Asked for with the hash the file has now, a file is answered `public, max-age=31536000,
immutable` — public, because the files are: the login page links them. Asked for with
another hash — a page loaded before an upgrade, asking by the name it holds — the file
there is is sent with `no-cache`, so a browser does not keep the new content under
the old name. Asked for with none, the answer is what it was.

### 4. A file is hashed when it is asked for, and again when it has moved

Not once at import: a file's size and modification time are read each time, and the
content is hashed again when either moved. An edit to the stylesheet shows on the next
page without a restart, which is what the edit loop of the live demo needs, and a page
costs a `stat` for each file it links.

### 5. A page and every part it fetches state one digest of the whole set

One digest over every stylesheet and script we ship, by name and hash, and over the
hashes of what the registered packages ship. A page that refreshes itself states it
on the script that does the refreshing (`data-assets`); every answer to that refresh
states the server's in `X-Assets`, beside `X-Rendered-At`.

### 6. Where they differ, the page loads itself afresh

The answer is not swapped in — it was written for other files — and the page reloads.
Three limits:

- **It waits for an open editor**, as every refresh does
  ([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) decision 7): while one
  is open nothing is fetched, so nothing is compared, and what is being typed stays.
  The first refresh after it closes finds the difference.
- **Once for a digest.** The digest a page reloaded for is kept in the session's
  storage, and a page does not reload for it twice. A server that answers with two
  digests in turn — two workers either side of an upgrade — would otherwise reload a
  page every ten seconds; as it is the page reloads once and then shows what it is
  sent, on the files it has.
- **Not without that storage.** A page that cannot remember what it reloaded for
  keeps its files and goes on swapping.

## Consequences

- A wall display takes an upgrade by itself, within one refresh of the process that
  carries it answering.
- `/system` reloads the same way; a page that does not refresh itself has nothing to
  go stale against and takes the new files at its next load.
- The fixture sheet rewrites `/static/` to a relative path and keeps working: a
  browser reading a file drops the query.
- A test or a script that asks for `/static/js/poll.js` by its bare name still gets
  it.
- Nothing is promised about the query's name or the digest's length; neither is
  surface a package may read.

## Alternatives considered

- **Hashed URLs alone.** Enough for a page that is loaded afresh, and it leaves the
  wall on the old script — the case this was filed for.
- **A banner saying a newer version is running.** Polite on a desk and useless on a
  wall, where nobody reads it and nobody can act on it.
- **The hash in the path** (`/static/js/poll.1a2b3c4d.js`). It needs a route of our
  own in front of the framework's, and buys nothing a query does not on our own
  origin with no proxy rewriting URLs in between.
- **The release version in the URL.** It moves when nothing changed and stands still
  through an edit; a registered package's asset already answered this with content.
- **Hashing once at import.** One `stat` cheaper per file, and an edited stylesheet
  would be kept for good under the hash of the old one until a restart.
