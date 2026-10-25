# Checks

Each `*.yaml` / `*.yml` file in a `config/checks/` directory defines one check. The
monitoring engine loads them and schedules each at its own `frequency`.
(This page is about *authoring* checks in YAML; implementing a new check **type** —
the Python class behind `type:` — is
[`../docs/implementing-checks.md`](../../docs/implementing-checks.md).)

- Put your check configs directly in `config/checks/`. `checks` is one **aspect** of
  the deployment's configuration directory, alongside `nodes.yaml`, `settings.yaml`
  and the file- or directory-form `users` aspect
  ([ADR-0031](../../docs/adr/0031-deployment-config-directory.md));
  it is always a directory, because its unit of data is the file — one check per
  `*.yaml`.
- The built-in SSH / metrics checks ship their scripts **inside the package**
  ([ADR-0021](../../docs/adr/0021-script-resolution.md)); you only add a `script:` to
  point at **your own** script (resolved relative to the config file's directory).
  `LITTLE_SISTER_SCRIPTS_DIR` relocates where a built-in default is looked up.
- `config/checks/examples/` holds copy-me templates and is **not** loaded
  (sub-folders are ignored).
- `LITTLE_SISTER_CONFIG_DIR` selects the configuration directory — or a **path-list**
  of them joined by your OS path separator (e.g. `base:sites/alpha`), whose
  `checks/` directories load as a **union** (a shared base plus site-specific adds).
  Every listed root must exist and **at least one** must provide `checks/`, or the
  process refuses to start; a `checks/` that exists but is still empty is allowed and
  says so on the dashboard. The set is read once at **startup** (a restart re-reads
  it).
- Two checks may share a host node only if they own **disjoint** subtrees — e.g.
  `host-metrics` + `qnap-metrics` on one host, or a `file` heartbeat as a sibling
  child. Two checks that own the **same** node (or one nested inside another's) are
  a hard error that names the path and files. See
  `docs/adr/0015-check-discovery-union.md`.

## Common fields

Every text below is Markdown as GitHub writes it, its tables and strikethrough among it,
and so is every line a check writes and a maintenance note; one renderer draws them all,
so a text is drawn alike wherever it is read whole, in a card, a line or a handbook. A
status written in braces — `{ok}`, `{warn}`, `{error}`, `{maintenance}` or
`{undefined}`, in either case — is drawn as that status's sign, its cue and its word on
its tint, so `{error}: restart the gateway` says what to do when it fails; in code, or
escaped as `\{error}`, it stays as written.

| Field | Meaning | Default |
|-------|---------|---------|
| `type` | `http`, `file`, `command`, or an SSH check (`ssh-connect`, `ssh-command`, `ssh-script`, `host-metrics`, `qnap-metrics`, `macos-memory`) | required |
| `path` | the node's **absolute, slash-separated** path, e.g. `/system/alpha` (a segment may be an FQDN; the last segment is the node's name) | required |
| `description` | what the check reads or checks, in a sentence (Markdown): it stands first in the node's *About* card, muted, and in the hover card where the node has no `about`; one past about 160 characters is warned about at startup | `""` |
| `about` | where the thing the node stands for is, how to reach it and what to do — an instruction, in short (Markdown): it stands in the node's *About* card beside its facts on its Status tab, and its first paragraph in the hover card, so a sentence or a few: one past 400 characters is warned about at startup. `nodes.yaml` overrides it | `""` |
| `title` | a **short** display label for the node (briefer than `about`); Markdown. `nodes.yaml` overrides it | `""` |
| `handbook` | what your team writes **at length** about the node — its runbook, how to sign in, its policy (Markdown) — read on the node's own **Handbook** tab, where its headings are anchored as GitHub anchors them, `## Sign in` at `#sign-in`. A single line ending in `.md` names a Markdown file, relative to this configuration root — `handbook: handbook/web.md` is `config/handbook/web.md` — and anything else is the text itself (see [A node's handbook](#a-nodes-handbook--confighandbook)). `nodes.yaml` overrides it | `""` |
| `details` | named values whose **keys your team chooses** — whom to ask, where tickets go, the documentation, a place, how to log in — each a line of Markdown, in the node's *About* card as a table beneath its `about`. What you give a node **holds for every node beneath it**, key by key, the nearest winning; a value YAML reads as anything but text — `12`, `0123`, `12:30`, `no` — refuses the start, naming the key, so quote it (see [A node's details](#a-nodes-details)). `nodes.yaml` overrides it key by key | none |
| `tags` | the node's **tags** — words that say what it is, `production`, `rack-4`, `customer-facing` — a list or one word, lowercase letters and digits with hyphens between them (capitals read as lower case). What you tag a node **holds for every node beneath it**, and every place that tags a node adds to the others — `nodes.yaml` overrides nothing here (see [A node's tags](#a-nodes-tags--configtagsyaml)) | none |
| `order` | this node's **declared rank among its siblings**: the row sorts by `(order, name)`, so a negative number pulls a node ahead of its unranked siblings and a positive one pushes it after them. A whole number, negative allowed; `nodes.yaml` overrides it, and both beat a rank the check's own result declares | unstated (sorts as `0`) |
| `show_when_quiet` | `true` when this node's **quiet lines are still information** — an inventory whose list is read *because* everything is fine. The wall then opens its box whatever its parent's ▤ says or its level starts as, and no fold the configuration sets hides it or its quiet lines; a viewer's press still does. `nodes.yaml` overrides it; must be a real boolean (`"false"` in quotes fails the load rather than reading as *on*) | unstated |
| `chips` | whether this node's **children start as chips** on the wall, each closed to its name and counts until it is clicked: `true` the compact look, `false` every child open. A child that claims `show_when_quiet` starts open whatever it says, and in each card the first three failures a chip would hide open their way, errors before warnings, with the nodes above them. Its type may propose it; what you write beats that, and `nodes.yaml` beats both, per path. A real boolean, or the start is refused, naming the file | the type's word, else `chips` in `settings.yaml`, else open — but a level that, opened, would draw more than thirty boxes starts as chips |
| `fold_ok` | whether this node's **healthy children and lines start folded** behind *✓ +N ok*, which a click shows: `true` the compact look. What claims `show_when_quiet` stays out of it. The same order and the same refusal as `chips` | the type's word, else `fold_ok` in `settings.yaml`, else shown |
| `reason_cap` | this node's box's **line budget** on the wall, its failing lines first and the rest a click away behind *⌄ all N*. A whole number, `0` its lines all behind it; a bad value refuses the start, naming the file | the type's word, else `reason_cap` in `settings.yaml` (6) |
| `children` | `chips`, `fold_ok`, `reason_cap` and `show_when_quiet` for **each child** of this node, whatever its name — how a look reaches a level a run names, the accounts or queues no name entry can; a child's own entry beats it. A block, under the top level or a `subnodes:` entry, never directly under `subnodes:` | — |
| `frequency` | how often to run — `30s`, `15m`, `2h`, `1d`, or a number of seconds | `15m` |
| `timeout` | per-run timeout (same duration format) | `30s` |
| `series_keep` | how many readings of each thing the check reads — a URL, a host — it keeps as that thing's **history**, the oldest dropped first, and a restart keeps them. A whole number; `0` keeps none, and there is no deployment-wide default, because where a history is wanted is a choice per check. What every history together may weigh is bounded by `series_limit` in `settings.yaml` | `0` |
| `measures` | which fields of what the check read are **drawn** as curves, over the readings `series_keep` keeps — each field by the dotted name its record list shows (`response_ms`, `timing.total_ms`), mapped to its **unit** or to `{unit, label, node}`. `node` is the node the curve stands on, a path from the check's own (`memory`, `disk/root`), which it stands on where it names none; every curve at or beneath a node is on that node's **Series** view. A `*` in the field picks every key of the things a record counts by name, and stands for it in the node and the label too: `volumes.*.avail_kb: {unit: KiB, label: Free space on *, node: disk/*}` is a curve per volume, on that volume's node. A unit is free text; `ms` and `s` are written as spans (`1.9 s`), `B`, `KiB`, `MiB`, `GiB` and `TiB` as sizes (`18.3 GiB`). A type may declare its own — `http` draws `response_ms` in `ms`, and `host-metrics`, `qnap-metrics` and `macos-memory` the numbers they grade — and this block merges over them per field: naming a field takes it whole, `field: null` draws it no more, and every field it does not name keeps the type's. A block of another shape refuses the start, naming the file | the type's |
| `reading_cap` | how many of those readings — the newest — the Series view lists of each series beneath its curves; every one is on the **History** page of the check's node. A whole number, `0` the curves alone; a bad value refuses the start, naming the file | `reading_cap` in `settings.yaml` (10) |
| `display` | what the check's **lines say**, re-worded: a **form**'s full name — the sentence the type's grading chose for a line, which the node's page shows beside it and `/system/installed` lists with its default text — mapped to a template that re-words it, `{line.default}` standing for the type's own text. A template names a field of what the check read by its dotted name, `{completed.url}`, and a word the type hands over as `{line.why}`; `{? …}` is shown only when every value it prints is there and `{?name: …}` when `name` is as well; a link is Markdown, `[words]({completed.url})`; `{{` writes a brace, and `}}` does outside a segment. A time under `at`, `started` or `ended` reads in the configured zone, and a value that is not there as `—`. A name that is no form of the type, and a template naming a field or a word the type does not declare, refuse the start, naming the file. None of the built-in types writes its lines as forms; the window's two, `since_ok.last` and `since_ok.none`, are the library's, on every check | the type's own |
| `max_since_ok_warn`, `max_since_ok_error`, `max_since_ok_reason` | **the window**: how long a subject — the URL, the file, the host — may go without a reading that stood OK, over the readings `series_keep` keeps, each level the last span that passes (`26h`); beyond it a line of its own says so on the node, at the level's code, the reason after it. Every type takes it. A level on a check that keeps nothing refuses the start, and one beyond what the check keeps is said in the log at start. `display:` re-words its two lines, `since_ok.last` and `since_ok.none`, over `{line.since}`, `{line.level}` and `{line.reason}` | not graded |

A non-`OK` result always carries a reason. A failed or timed-out run becomes
`ERROR` (ADR-0040 / ADR-0001).

## What a check grades by

What a check type grades — a disk's use, a file's age, an HTTP status — the type
declares, and `/system/installed` lists with its default and its keys. A deployment
writes it in one spelling per kind, among the check's own keys or in the block of what
it grades
([ADR-0131](../../docs/adr/0131-a-type-declares-what-it-grades-and-the-library-grades-it.md)):

- **A pair** of levels over a number, `<key>_warn` and `<key>_error`, each level the
  last value that passes: a `max_…` pair fails above its levels and a `min_…` pair
  below them. A level is written in the unit the type declares — a count, a number, a
  duration (`20m`), a size (`4 GiB`), an amount, or a share with its percent sign
  (`80%`). Writing any key of a pair takes the pair as written, so a level you leave
  out is not compared, whatever the type's default; `<key>: null` switches the
  judgment off, and the value is still shown. Equal levels, and an error level that is
  not beyond the warning, refuse the start.
- **A map** from a word of its source's vocabulary to a code, under the key its type
  declares. A word matches with its case and the spaces around it folded, a map you
  write merges over the type's word by word, a key naming no word the type knows is
  said once in the log at start and grades as written, and a word no key names grades
  `WARN`.
- **A set** of accepted values, as `http`'s `expected_status`: any other value fails.
- **`<key>_reason`**, beside a pair, a set or a judgment the type makes in its own
  code, is the sentence the line says after its own text where that grading decided
  it.

A key that does not fit refuses the start, naming the file and the key, and so does
one of the keys these replaced — `thresholds:`, `warn_mb` and `error_mb`, and the
`file` check's `max_age` with a level and `stale_code` — naming what to write instead.

## Node metadata — `config/nodes.yaml`

An **optional** `nodes.yaml` **beside** this directory — one per configuration root,
not inside `checks/` — declares each node's `about`, `title`, `handbook`, `details`,
`tags`, `order` and `show_when_quiet` keyed by its absolute
path, so it can reach **container / host** nodes that no single check owns. It is
layered across the roots and seeded at startup: a later root wins **per field** over
an earlier one (the override is logged, naming both files), and a `nodes.yaml` value
wins over the inline value on a check, also per field — and `details` per key; `tags`
add up instead, every root's and every check's. A bare string is shorthand for
`about`. A declared path that no check covers is warned about at startup, and so is
an `about` past 400 characters
([ADR-0012](../../docs/adr/0012-node-metadata.md) /
[ADR-0017](../../docs/adr/0017-node-title.md) /
[ADR-0055](../../docs/adr/0055-sibling-order.md)).

```yaml
/system/alpha:
  title: Living-room NUC
  about: Intel NUC in the hallway cupboard; Debian 12.
  handbook: handbook/servers.md  # on its Handbook tab, a file of this root's handbook/
  order: 1                       # ranked, so it sorts *after* every unranked sibling
/nexus:
  title: Nexus NAS
  about: QNAP TS-453D NAS, 4× 8 TB in RAID-5.
  order: 2                       # …so rank the whole set, or use negatives to lead
/aws/prod/ec2:
  show_when_quiet: true          # its instance list is the reading
/aws/prod/cloudwatch:
  show_when_quiet: false         # …and this one declines what its check declared
```

**A stated value is not an absent one**, and for both of the fields above that is
the whole point of writing them here.

Writing `show_when_quiet: false` is not the same as leaving it out. An absent key is
*nobody said*, so a check type that ships the declaration still reaches the node; a
stated `false` occupies the field and takes that declaration back
([ADR-0063](../../docs/adr/0063-declining-the-density-trade.md)).

`order: 0` is the same move for a rank — the only way to overrule a rank a check
declared, by naming the value an unranked node already carries. It is **not** a
request for alphabetical order: `0` is the rank the unranked carry, so a zeroed node
sorts *with* them — after every negative rank, before every positive one. Zeroing one
child of a set its check ranked `1..5` therefore moves it to the **front** of that
set; putting the whole set back in alphabetical order takes an `order: 0` on every
sibling ([ADR-0055](../../docs/adr/0055-sibling-order.md)).

## A node's handbook — `config/handbook/`

A node's **handbook** is what your team writes at length about it — its runbook, how to
sign in, its policy, the reference a package ships — where its `about` holds the short
account. It is read on a tab of its own, *Handbook*, which stands on every view of a node
that has one, after *History* and before *Copy*, and the hover card links it
([ADR-0133](../../docs/adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)).
It renders as every text does, its tables and a status in braces, `{error}`, among it
(see [Common fields](#common-fields)), and its headings are anchored as GitHub anchors
them, so `[Sign in](#sign-in)` leads to `## Sign in`.

Write it as text, or keep it as a Markdown file in `config/handbook/` and name the file:
a single line ending in `.md` names one, and anything else is the text itself. A file is
named where the handbook is stated — a check's own `handbook:`, an aspect's under
`subnodes:`, or a path's in `nodes.yaml` — **relative to the configuration root that
file is in**, and never found by a node's path, so three accounts' `ec2` share one
runbook:

```yaml
# config/checks/aws_prod.yaml
subnodes:
  ec2:
    handbook: handbook/ec2.md     # config/handbook/ec2.md, for every `ec2` beneath
# config/nodes.yaml
/aws:
  handbook: |
    ## Sign in

    Through the SSO portal, with the role your team was given.
```

A handbook is a label as the `about` is, from the same places in the same order:
`nodes.yaml` over the check's file over what the check type ships. A type may ship one
for the aspects it emits — the library's `host-metrics`, `qnap-metrics` and
`macos-memory` ship one an aspect — and `{default}` in yours places it: your sign-in and
policy before its reference, or after. The startup node names a file a handbook names
that is missing, unreadable or outside its root, which gives no handbook, and a file in
`handbook/` that nothing names. A handbook is read with the rest of the configuration:
an edited one reaches the running instance at its next restart.

**Any text of a node links its handbook by a short form**: `handbook` for its top, and
`handbook#<section>` for a section — a heading, anchored as above. So an `about` keeps
the short version and points into the long one, and a text said of every node of a
name — an aspect's under `subnodes:`, a type's description — leads each node into its
own:

```yaml
subnodes:
  ec2:
    about: "{error}: [what to do](handbook#when-it-fails)"
    handbook: handbook/ec2.md
```

The page opens the node's handbook there, and a Copy document writes the link out to
the handbook's full address. The startup node names a link that leads nowhere — to a
section the handbook does not have, or on a node that has none: for a check's own node
and the nodes above it at the start, and for a node beneath when a run first fills it.

## A node's details

A node's **details** are named values whose keys your team chooses, each a line of
Markdown: whom to ask, where its tickets go, its documentation, a provider, a place, how
to log in. Its *About* card shows them as a table beneath its `about`, the key muted
([ADR-0133](../../docs/adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 6). A check type gives each node it writes the details of its object — an
account, a region, a function, a host — with every run; you give anything else, in the
check's file for its own node, under an aspect's name in its `subnodes:` block, and in
`nodes.yaml` by path, which wins key by key.

**What you give a node holds for every node beneath it**, key by key, the nearest
winning. So a place told level by level composes itself card by card, a contact holds
for a subtree that one key overrides lower down, and how to log in to a server is
written once — and the details under an aspect's name reach every node a run names
beneath it, a function or a volume, which nothing written for a name reaches:

```yaml
# config/nodes.yaml
/aws:
  details:
    contact: "[Platform on call](https://ops.example.org/oncall)"
    tickets: PLAT
/aws/live:
  details:
    contact: "[Live on call](https://ops.example.org/live)"  # the row stays where /aws put it
# config/checks/aws_live.yaml
subnodes:
  lambda:
    details:
      login: "[sign in](handbook#sign-in)"   # this node's handbook, for every function
```

In the card the type's details stand first, in its order — the object — then yours, the
outermost first and the node's own last; a key stands once, where it is named highest,
with its nearest value, and a key given down names the node it comes from as its
tooltip. A key written with no value — `tickets:` — is a value too: the row stands
nowhere there or beneath, where nothing nearer names it. A link a detail writes in the
short form leads into the handbook of the node it is given on, a page every node
beneath shares, and the startup node names one that leads nowhere. A value is kept as
written, so one YAML would read as anything but text — `12`, `0123`, `12:30`, `3.10`,
`no` — refuses the start, naming the key: quote it. A node's Copy document carries its
card's table, the links written out.

## A node's tags — `config/tags.yaml`

A node's **tags** are words that say what it is where the tree cannot — its
environment, a place, an owner, whether it faces customers: `production`, `berlin`,
`rack-4`, `customer-facing`. Never what it is doing — failing, pinned, stale — and never
a policy: whether a production failure wakes somebody is a rule over the tag, not a tag
`page` ([ADR-0139](../../docs/adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md)).
You write them where you write a node's details: `tags:` in the check's file for its own
node, under an aspect's name in its `subnodes:` block, and in `nodes.yaml` by path.

**A node carries every tag written for it or for a node above it**, and nothing adds up
the other way: a parent never carries its children's. Every place that tags a node adds
to the others — no place wins, a later root adds to an earlier one's, and nothing takes
a tag back — so one tag on `/aws/live` is the whole account:

```yaml
# config/nodes.yaml
/aws/live:
  tags: [production, eu-central-1]
# config/checks/aws_live.yaml
subnodes:
  ec2:
    tags: compute            # the ec2 this check writes, and everything beneath it
```

`config/tags.yaml` names the **known tags**, each with one line of what it means, in the
order the wall offers them and a node lists them; every root's file is read and they add
up, the later root's line winning for a tag two of them name:

```yaml
# config/tags.yaml
production: Serves customers; a failure here is somebody's outage.
eu-central-1: In Frankfurt.
compute: Runs instances.
```

A tag is lowercase letters and digits with hyphens between them; capitals are read as
lower case, so `Production` is `production`, and one with any other character is not
read — the startup node names it and where it is written. A tag the file does not name
still applies, and the startup node names it once with where it is written; so it does
every tag, while no root has the file. A node's *About* card shows its tags as a line of
chips between its `about` and its details, each one's tooltip what it means and, where
it comes down from above, the node it is written on; the hover card and the Copy
document name them too, and the JSON API carries every tag a node carries as `tags`.

**A tag selects.** The wall shows only what carries one tag — the band's list, or
`?tag=production` in the address — each part that carries it a card of its own; the
Events page takes `?tag=` too. A configured rule (`config/aggregation.yaml`) and an
action (`config/actions.yaml`) write `tag:` beside `under:` or instead of it, both
holding where both are written; a rule by a tag acts where the tag begins. A `tag:` that
no node is given anywhere in the configuration is refused at the start, and the startup
node names it.

## `http`
GET a URL; OK when the response status matches.

```yaml
type: http
path: /website                # absolute node path (ADR-0016)
url: https://example.com
expected_status: 200      # int or list, e.g. [200, 204]; any other status is ERROR
# expected_status_reason: "Only a 200 means the database answered."
follow_redirects: true    # default; set false to read a 3xx as the answer
frequency: 5m
```

`follow_redirects` decides what a `3xx` means, and the two readings differ on the same
URL. Followed (the default, and what this check has always done) the status is whatever
answers at the end of the chain — so a moved site keeps reporting OK, and so does a
login wall answering `200`. Reported, the `3xx` **is** the reading: list the redirect
codes you accept in `expected_status`, and a new one turns the check. It must be a real
boolean; `"false"` in quotes is refused at load rather than read as true.

## `file`
Heartbeat: OK while a file keeps being updated; stale otherwise. How old it may be is a
pair, `max_age`: an error above twenty minutes where you write neither level.

```yaml
type: file
path: /nightly-export         # absolute node path (ADR-0016)
file: logs/app.done                   # absolute, ~/…, or relative to your $HOME
max_age_error: 20m                    # ERROR once the file is older than this
# max_age_warn: 10m                   # WARN once it is older than this
# max_age_reason: "The export runs every quarter of an hour."
# max_age: null                       # grade nothing; the age is still shown
```

## `command`
Run a command/script; OK on exit code 0. The reason is the captured output.

```yaml
type: command
path: /disk-space             # absolute node path (ADR-0016)
command: bash check-disk-space.sh   # your script (cwd = working_dir); or a list (argv)
capture: both          # stdout | stderr | both
max_chars: 1000        # shorten captured output…
keep: tail             # …from the tail (default) or head
working_dir: .         # optional; defaults to the check config's directory
```

## The SSH check family

Five checks run over one SSH connection and share its config — `host`, `user`,
`port`, `identity_file`, `options`, `sudo`, `timeout`. `BatchMode` is forced
(non-interactive, key-based auth; the host key already known) and the legacy SHA-1
`ssh-rsa` algorithm is **off by default**. When ssh flags an advisory — notably a
**non-post-quantum key exchange** — the connecting check surfaces it as **WARN**:
`ssh-connect`, `ssh-command` and `ssh-script` on their result, `host-metrics` on
its `ssh` leaf. (`qnap-metrics` shares a host node with `host-metrics` and leaves
the warning to it.) A host that can't offer a PQ key exchange (e.g. an old
Dropbear) silences it with `options: ["-o", "WarnWeakCrypto=no-pq-kex"]`.

### `ssh-connect`
Reachability: connect and report OK if reachable, ERROR if not (WARN on a non-PQ
key-exchange advisory).

```yaml
type: ssh-connect
path: /myhost                 # absolute node path (ADR-0016)
host: server.example.net   # required — a ~/.ssh/config alias or hostname/FQDN
frequency: 1m
```

### `ssh-command`
Run a remote command — the over-SSH twin of `command`. OK on exit 0; reason = the
captured output (`capture`: `stdout` | `stderr` | `both`, shortened to `max_chars`
from `tail` / `head`).

```yaml
type: ssh-command
path: /myhost-disk            # absolute node path (ADR-0016)
host: server.example.net
command: df -h /           # the host's shell runs this string
capture: both
```

### `ssh-script`
Pipe a local script to the host and report its output (same output options as
`ssh-command`). `host-metrics` and `qnap-metrics` are parsing specialisations.

```yaml
type: ssh-script
path: /myhost-check           # absolute node path (ADR-0016)
host: server.example.net
script: my-check.sh           # your script, relative to this config's directory
interpreter: bash             # default bash; sh for busybox
```

## `host-metrics`
Read basic system parameters from a host over SSH. Point the check at the **host
node** (its absolute `path`); it populates that node with an `ssh` **transport leaf**
plus one leaf per metric (`disk`, `memory`, `cpu`, `load`), all **siblings** —
ssh is only the helper that fetches the data, not its parent. The `ssh` leaf is
OK normally, **WARN** when ssh prints an advisory (e.g. the post-quantum
key-exchange notice), and ERROR on a failed connection; each metric carries its
number even when OK and is graded by a pair of its own — `max_disk`, `max_memory`,
`max_cpu`, `max_load`. `disk_path: all` (or a **list**
of paths) makes `disk` a branch with one graded child per filesystem (named by its
volume, e.g. `root`, `MD0_DATA`), the fullest rolling up — a list monitors just
those volumes (handy for skipping a NAS's near-full firmware partitions). One
connection per run pipes a metrics script to the host's shell; the host's
`profile` (`linux`, `macos` or `busybox`, default `linux`) selects the script and
the interpreter (`bash`, or `sh` for busybox), and the script only measures while
this check grades. Each script self-checks the host (its OS
family, and the linux profile also rejects a busybox userland) and reports a
clear config error (a WARN on the `ssh` leaf) if the `profile` is wrong. Auth
must be non-interactive
(`BatchMode`): set up key auth and a known host key first. The metrics need no
root. The legacy SHA-1 `ssh-rsa` algorithm is **off by default** for every host;
a host that still needs it can re-enable it with
`options: ["-o", "PubkeyAcceptedAlgorithms=+ssh-rsa"]`.

```yaml
type: host-metrics
path: /system/alpha          # absolute node path (ADR-0016)
host: server.example.net   # required
frequency: 2m
# profile: linux           # host OS/userland: linux (default) | macos | busybox
#                          #   selects the metrics script + interpreter (sh for busybox)
# user: monitor            # default: your local SSH user
# port: 22                 # default: SSH default
# sudo: false              # run the script under `sudo -n` (not needed for these)
# identity_file: ~/.ssh/id_ed25519
# options: ["-o", "StrictHostKeyChecking=accept-new"]   # extra ssh args
# debug: true              # add raw ssh stderr + df diagnostics to the ssh leaf
# disk_path: /             # filesystem to measure (default: / — or
#                          # /System/Volumes/Data for the macos profile)
#                          # `all` → every real filesystem as a `disk` branch;
#                          # a list → just those volumes as a `disk` branch, e.g.
#                          #   disk_path: [/share/MD0_DATA, /share/HDB_DATA]
# script: my-host-metrics.sh   # your own script, overriding the profile default
# Each aspect is a pair: above `_warn` → WARN, above `_error` → ERROR (defaults shown)
# max_disk_warn: 80%       # percent used, each volume's alike
# max_disk_error: 90%
# max_memory_warn: 85%     # percent used
# max_memory_error: 95%
# max_cpu_warn: 85%        # percent busy
# max_cpu_error: 95%
# max_load_warn: 0.8       # 1-min load average per CPU core
# max_load_error: 1.0      # `max_load: null` grades the load not at all
# descriptions:            # per-leaf description (Markdown), keyed by leaf name
#   disk: The share of the NVMe drive's space in use, as `df` reports it.
```

Each leaf's `description` says what it reads, in a sentence: the `descriptions:` map's
(by leaf name — `ssh`, `disk`, `memory`, `cpu`, `load`), or the type's own; the shared
host node's own description stays empty so two checks can share it
([ADR-0012](../../docs/adr/0012-node-metadata.md)).

Each aspect also ships an **`about`** that says what to do when it warns or fails, by
the status it is done on — *{warn}: find what grows and clean it up, or plan more
space* — and a **handbook** that says it at length: how to read the value, its levels,
and what to do, step by step, the about linking its sections
([ADR-0133](../../docs/adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)).
To retune either for your hosts, add a **`subnodes:`** block keyed by leaf name
(`subnodes: {disk: {about: "…", title: "…", handbook: handbook/disk.md}}`): a config
entry overrides the shipped one per field; an omitted field keeps it, and `nodes.yaml`
still overrides above both, per node path
([ADR-0025](../../docs/adr/0025-check-provided-subnode-metadata.md); for a handbook see
[A node's handbook](#a-nodes-handbook--confighandbook)). Write `{default}` inside your
text to **extend** the shipped text instead of replacing it — your policy before it,
after it or around it — and the type's own `{token}`s (a team name, a severity legend)
expand in either. A status in braces, `{error}` and the other four, is no token: the
page draws it as that status's sign.

**`little-sister` itself reads this block**, for every branch check type: the type
declares its defaults and the library resolves yours over them, so an entry here works
whatever the type is and needs no release of it. Entries apply by subnode *name* —
every leaf named `disk`, on every host this check reports, at any depth. A volume is
no aspect, and no entry reaches it by its name, whatever the host calls it: where
`disk_path` is `all` or a list, a filesystem mounted at `/mnt/memory` is a volume named
`memory`, and takes nothing you write for the `memory` leaf. Label a volume by its path,
in `nodes.yaml`
([ADR-0118](../../docs/adr/0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)).
A volume carries its mount point among its details, and what holds for every volume of a
host — whom to ask, what may be deleted — you write once, as `details` in the `disk`
entry, which reach every volume beneath it ([A node's details](#a-nodes-details)).

The same block carries the keys of how a node first looks, beside its labels. The first
is **`show_when_quiet`** (`subnodes: {disk: {show_when_quiet: true}}`), the per-aspect
form of the common field above — *this leaf's quiet lines are still information*, so the
wall keeps its box open and its lines in sight. It resolves like the labels beside it:
what you write here beats what the check type declared for that name — a type declares
the flag for an aspect that is a roster *by construction*, so you may never need to
write it at all — and `nodes.yaml` still overrides both, per node path
([ADR-0063](../../docs/adr/0063-declining-the-density-trade.md)). Writing
`show_when_quiet: false` is how you decline a declaration a type ships; leaving the key
out says nothing. **`chips`**, **`fold_ok`** and **`reason_cap`**, the common fields
above, take the same addresses — `subnodes: {backup: {chips: true}}` starts every
`backup` node's children as chips — and resolve the same way: your entry over the
type's, `nodes.yaml` over both, and `settings.yaml` beneath them all, for what nobody
spoke for ([ADR-0128](../../docs/adr/0128-where-a-nodes-first-look-comes-from.md)).
Under **`children:`** each of them speaks for each child of a node, whatever its name —
`subnodes: {queues: {children: {show_when_quiet: true}}}` for every queue a run names,
which no name entry reaches, or a top-level `children: {chips: false}` for each child of
the check's own node — and a child's own entry beats it, as it beats what a run stamps;
a `nodes.yaml` path takes a `children:` too. A key an entry or a `children:` block does
not know is named in one startup line for the file, where it used to do nothing in
silence.

**`host-metrics` proposes a host's leaves as chips**, five short readings on every host
of a wall, and a disk's filesystems where `disk_path` fans it out: each chip shows its
state, and a failing one opens by its card's budget of three. Take it back with
`chips: false` at the file's top level for a host's leaves,
`subnodes: {disk: {chips: false}}` for a disk's filesystems, or per path in
`nodes.yaml`. On a host node another check shares it speaks for its own leaves alone
(below).

A check that reports several nodes like this returns a small tree of results
(`CheckResult.children`); the engine writes each as a node under the check's node
([ADR-0007](../../docs/adr/0007-check-result-branches.md)).

## Several metrics checks on the same host

The `host-metrics`, `qnap-metrics` and `macos-memory` checks share their SSH
connection handling, and **all can target the same host node** — give them the
same `path` and they sit side by side (their leaf sets are disjoint). Give the
*secondary* ones no `description` so they don't overwrite the host's.

A host node they share is neither one's: its own look — its fold, its line budget — is
`nodes.yaml`'s for that path, as a container's is. Each of its leaves starts as the check
that writes it says of the leaves of its own node: `host-metrics`' and `macos-memory`'s
as chips, as each proposes, while `qnap-metrics` proposes nothing for the node, so its
`smart` and `temperature` stand open beside `host-metrics`' chips. A check's file takes
back its own leaves alone — `chips: false` at the top of `host-metrics`' file opens
`ssh`, `cpu`, `memory`, `load` and `disk` and leaves `macos-memory`'s `swap` a chip — and
`chips:` for the path in `nodes.yaml` says it for every leaf at once, before either.
Beneath the leaves each check speaks for its own branches, `disk`, `smart`,
`temperature` and `processes`
([ADR-0128](../../docs/adr/0128-where-a-nodes-first-look-comes-from.md) decision 5, as
amended).

## `qnap-metrics`
QNAP hardware health over SSH (QTS `getsysinfo`): a `temperature` branch
(`system`, `cpu` where the model has a sensor, and one `drive<bay>` per populated
bay, in °C, graded by the pair `max_temperature`) and a `smart` branch (one
`drive<bay>` per bay: `GOOD`→OK, `Warning`→WARN, else ERROR, a judgment `smart_reason`
says a sentence for). Empty bays and absent sensors are skipped. Each branch ships an
`about` that says what to do and a handbook that says it at length, as `host-metrics`'
aspects do, and a drive carries its bay among its details. It proposes the drives and
the sensors as chips, the two branches open; `subnodes: {smart: {chips: false}}` takes
one back ([ADR-0128](../../docs/adr/0128-where-a-nodes-first-look-comes-from.md)).

```yaml
type: qnap-metrics
path: /nexus                  # absolute node path (ADR-0016)
host: nexus62            # required
frequency: 2m
# (no description — it shares the host node with the host-metrics check)
# user / sudo / port / identity_file / options — same as the host-metrics check
# max_temperature_warn: 50     # °C (system, cpu and each drive); defaults shown
# max_temperature_error: 60
# smart_reason: "Replace the drive before the next one goes."
# descriptions:            # per-leaf description, keyed by leaf name
#   temperature: The chassis's and the drives' temperatures in °C.
```

## `macos-memory`
macOS memory health over SSH — the early-warning signals that RAM trouble is
*building*, beyond `host-metrics`' single memory percentage: `pressure` (the
kernel's VM memory-pressure level: normal→OK, warning→WARN, critical→ERROR),
`swap` (MB in use), `compressor` (memory occupied by the compressor as % of
RAM — compressor exhaustion is the kernel-panic signature on a small-RAM Mac),
and optionally `processes` — one leaf per watched command-line pattern with its
resident memory (RSS, summed over matching processes) and the oldest match's
uptime, so a slow leak shows as monotonic RSS growth long before pressure
moves, and a scheduled app restart shows as the uptime resetting. A watched
process that isn't
running reports **OK** ("not running"): this check watches memory, not
liveness — pair it with a `file` heartbeat or `ssh-command` for that. The
script self-checks it's on Darwin and reports a clear config error otherwise. Each
aspect ships an `about` that says what to do and a handbook that says it at length, as
`host-metrics`' aspects do — the watched processes their branch's — and a watched
process carries its pattern among its details. It proposes its leaves as chips —
`pressure`, `swap`, `compressor` and the `processes` branch — and the watched processes
beneath it too; `chips: false` at the file's top
level takes back the leaves and `subnodes: {processes: {chips: false}}` the processes
([ADR-0128](../../docs/adr/0128-where-a-nodes-first-look-comes-from.md)).

```yaml
type: macos-memory
path: /macmini/system         # absolute node path (ADR-0016)
host: macmini              # required
frequency: 2m
# (no description — it shares the host node with the host-metrics check)
# user / sudo / port / identity_file / options / debug — same as host-metrics
# script: my-memory.sh   # your own script, overriding the default
# processes:               # watch these processes' RSS (omit for none)
#   - name: findmy         # leaf name under `processes`
#     pattern: FindMy.app  # substring of the full command line (`ps axo command`)
#     max_rss_warn: 1 GiB  # its resident memory, summed (default: 1 GiB / 2 GiB)
#     max_rss_error: 2 GiB
# Each is a pair: above `_warn` → WARN, above `_error` → ERROR (defaults shown). The
# pressure is the kernel's own level — 1 normal, 2 warning, 4 critical.
# max_pressure_warn: 1
# max_pressure_error: 2
# max_swap_warn: 4 GiB     # swap in use
# max_swap_error: 8 GiB
# max_compressor_warn: 35% # of physical RAM
# max_compressor_error: 50%
# descriptions:            # per-leaf description, keyed by leaf name
#   compressor: The compressor's share of the memory, this Mac's panic precursor.
```
