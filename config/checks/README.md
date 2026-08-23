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

| Field | Meaning | Default |
|-------|---------|---------|
| `type` | `http`, `file`, `command`, or an SSH check (`ssh-connect`, `ssh-command`, `ssh-script`, `host-metrics`, `qnap-metrics`, `macos-memory`) | required |
| `path` | the node's **absolute, slash-separated** path, e.g. `/system/alpha` (a segment may be an FQDN; the last segment is the node's name) | required |
| `description` | human-readable description of what the check *does* (Markdown) | `""` |
| `about` | subject metadata — what the node *is* (location, kind, context); Markdown. `nodes.yaml` overrides it | `""` |
| `title` | a **short** display label for the node (briefer than `about`); Markdown. `nodes.yaml` overrides it | `""` |
| `order` | this node's **declared rank among its siblings**: the row sorts by `(order, name)`, so a negative number pulls a node ahead of its unranked siblings and a positive one pushes it after them. A whole number, negative allowed; `nodes.yaml` overrides it, and both beat a rank the check's own result declares | unstated (sorts as `0`) |
| `show_when_quiet` | `true` when this node's **quiet lines are still information** — an inventory whose list is read *because* everything is fine. The dense dashboard then keeps its full box and never folds it behind *+N more*. `nodes.yaml` overrides it; must be a real boolean (`"false"` in quotes fails the load rather than reading as *on*) | unstated |
| `frequency` | how often to run — `30s`, `15m`, `2h`, `1d`, or a number of seconds | `15m` |
| `timeout` | per-run timeout (same duration format) | `30s` |

A non-`OK` result always carries a reason. A failed or timed-out run becomes
`ERROR` (ADR-0040 / ADR-0001).

## Node metadata — `config/nodes.yaml`

An **optional** `nodes.yaml` **beside** this directory — one per configuration root,
not inside `checks/` — declares each node's `about`, `title`, `order` and
`show_when_quiet` keyed by its absolute
path, so it can reach **container / host** nodes that no single check owns. It is
layered across the roots and seeded at startup: a later root wins **per field** over
an earlier one (the override is logged, naming both files), and a `nodes.yaml` value
wins over the inline value on a check, also per field. A bare string is shorthand for
`about`. A declared path that no check covers is warned about at startup
([ADR-0012](../../docs/adr/0012-node-metadata.md) /
[ADR-0017](../../docs/adr/0017-node-title.md) /
[ADR-0055](../../docs/adr/0055-sibling-order.md)).

```yaml
/system/alpha:
  title: Living-room NUC
  about: Intel NUC in the hallway cupboard; Debian 12.
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

## `http`
GET a URL; OK when the response status matches.

```yaml
type: http
path: /website                # absolute node path (ADR-0016)
url: https://example.com
expected_status: 200      # int or list, e.g. [200, 204]
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
Heartbeat: OK while a file keeps being updated; stale otherwise.

```yaml
type: file
path: /nightly-export         # absolute node path (ADR-0016)
file: logs/app.done                   # absolute, ~/…, or relative to your $HOME
max_age: 20m                          # OK if modified within this window
stale_code: ERROR                     # status when stale (default ERROR)
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
number even when OK and is graded by `thresholds`. `disk_path: all` (or a **list**
of paths) makes `disk` a branch with one graded child per filesystem (named by its
volume, e.g. `root`, `MD0_DATA`), the fullest rolling up — a list monitors just
those volumes (handy for skipping a NAS's near-full firmware partitions). One
connection per run pipes a metrics script to the host's shell; the host's
`profile` (`linux`, `macos` or `busybox`, default `linux`) selects the script and
the interpreter (`bash`, or `sh` for busybox), and the script only measures while
this check applies the thresholds. Each script self-checks the host (its OS
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
# thresholds:              # value at/above 'warn' → WARN, at/above 'error' → ERROR
#   disk:   {warn: 80, error: 90}     # percent used
#   memory: {warn: 85, error: 95}     # percent used
#   cpu:    {warn: 85, error: 95}     # percent busy
#   load:   {warn: 0.8, error: 1.0}   # 1-min load average per CPU core
# descriptions:            # per-leaf description (Markdown), keyed by leaf name
#   disk: Root filesystem on the NVMe drive
#   load: 1-minute load average per core
```

Each leaf's `description` comes from the `descriptions:` map (by leaf name —
`ssh`, `disk`, `memory`, `cpu`, `load`) or a built-in default; the shared host node's
own description stays empty so two checks can share it ([ADR-0012](../../docs/adr/0012-node-metadata.md)).

Each leaf also ships a built-in **`about`** — a short note on what the aspect
(`ssh` / `disk` / `memory` / `cpu` / `load`) measures and how it grades — shown in the
dashboard hover card. To retune one for your hosts, add a **`subnodes:`** block keyed by
leaf name (`subnodes: {disk: {about: "…", title: "…"}}`): a config entry overrides the
built-in default per field; an omitted field keeps the default, and `nodes.yaml` still
overrides above both, per node path
([ADR-0025](../../docs/adr/0025-check-provided-subnode-metadata.md)). Write
`{default}` inside your text to **extend** the shipped note instead of replacing it —
before it, after it or around it — and the type's own `{token}`s (a team name, a
severity legend) expand in either.

**`little-sister` itself reads this block**, for every branch check type: the type
declares its defaults and the library resolves yours over them, so an entry here works
whatever the type is and needs no release of it. Entries apply by subnode *name* —
every leaf named `disk`, on every host this check reports, at any depth.

The same block carries the one non-label key:
**`show_when_quiet`** (`subnodes: {disk: {show_when_quiet: true}}`), the per-aspect
form of the common field above — *this leaf's quiet lines are still information*, so
the dense dashboard keeps its box and never folds it. It resolves like the labels
beside it: what you write here beats what the check type declared for that name — a
type declares the flag for an aspect that is a roster *by construction*, so you may
never need to write it at all — and `nodes.yaml` still overrides both, per node path
([ADR-0063](../../docs/adr/0063-declining-the-density-trade.md)). Writing
`show_when_quiet: false` is how you decline a declaration a type ships; leaving the
key out says nothing.

A check that reports several nodes like this returns a small tree of results
(`CheckResult.children`); the engine writes each as a node under the check's node
([ADR-0007](../../docs/adr/0007-check-result-branches.md)).

## Several metrics checks on the same host

The `host-metrics`, `qnap-metrics` and `macos-memory` checks share their SSH
connection handling, and **all can target the same host node** — give them the
same `path` and they sit side by side (their leaf sets are disjoint). Give the
*secondary* ones no `description` so they don't overwrite the host's.

## `qnap-metrics`
QNAP hardware health over SSH (QTS `getsysinfo`): a `temperature` branch
(`system`, `cpu` where the model has a sensor, and one `drive<bay>` per populated
bay, in °C) and a `smart` branch (one `drive<bay>` per bay: `GOOD`→OK,
`Warning`→WARN, else ERROR). Empty bays and absent sensors are skipped.

```yaml
type: qnap-metrics
path: /nexus                  # absolute node path (ADR-0016)
host: nexus62            # required
frequency: 2m
# (no description — it shares the host node with the host-metrics check)
# user / sudo / port / identity_file / options — same as the host-metrics check
# thresholds:
#   temperature: {warn: 50, error: 60}   # °C (system, cpu and each drive)
# descriptions:            # per-leaf description, keyed by leaf name
#   temperature: Chassis and drive temperatures
#   smart: Per-drive SMART health
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
script self-checks it's on Darwin and reports a clear config error otherwise.

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
#     warn_mb: 1024        # per-process override (default: thresholds.process)
#     error_mb: 2048
# thresholds:              # value at/above 'warn' → WARN, at/above 'error' → ERROR
#   swap:       {warn: 4096, error: 8192}   # MB in use
#   compressor: {warn: 35, error: 50}       # percent of physical RAM
#   process:    {warn: 1024, error: 2048}   # default RSS MB for watched processes
# descriptions:            # per-leaf description, keyed by leaf name
#   compressor: Compressed-memory occupancy (panic precursor)
```
