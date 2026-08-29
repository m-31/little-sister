# ADR-0067 — The run scripts can serve TLS, and never verify it

- **Status:** Accepted
- **Date:** 2026-08-29
- **Related:** [ADR-0065](0065-the-connection-decides-what-is-secure.md) (what the
  application does once the connection is TLS),
  [ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) (what the probe
  now aims at), [ADR-0058](0058-transport-policy-vocabulary.md) and
  `little_sister.fetch` (the verification rule this is **not** an exception to)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

`start.sh`, `stop.sh` and `test_api.sh` are how somebody who receives little-sister runs
it, and all three could only ever speak `http://`. How to change that has been open for
a long time, with only one half of it ever leaning anywhere: gunicorn's own
`certfile`/`keyfile` rather than a proxy in front, because the simple install this
project protects is one process and one command. Everything else stayed open —
self-signed or an internal authority, where the pair comes from, and what a client has
to do about trust.

A deployment has since answered all of it for itself, in code, and the answers travel:
terminate in gunicorn, mint a throwaway certificate at every start, ask for it per run
rather than configuring it. What it does **not** answer is the half that only a library
has — somebody receiving these scripts may already own a certificate, from an internal
authority or a public one, and a design that can only mint would make that person's
setup the awkward case.

## Decision

### 1. `--tls`, on all three scripts

Not a setting in `instance.sh`, which is committed and would make one person's choice
everybody's default; and not an environment variable alone, which has to be unset again
and produces the shell three days old still serving a scheme nobody remembers choosing.
The flag is per run, which is what the choice is.

`LITTLE_SISTER_TLS` exists beside it for the case the flag cannot serve: telling
`stop.sh` or `test_api.sh` about an instance a script somewhere else started.

All three take it, but for two reasons rather than one, and the difference only became
visible later. `start.sh` and `test_api.sh` need the flag because they have to *speak*
the scheme: one binds it, the other opens a connection with it. `stop.sh` does not — it
sends a signal to a pid, and a pid has no scheme. It took the flag because it looked at
one port and would otherwise report a running instance as absent, which turned out to be
a worse answer than looking at both (§7). It still accepts the flag; nothing about which
instance it finds depends on it.

### 2. The port moves with the scheme

`TLS_PORT` in `instance.sh`, `8443` by default, beside the plain `PORT`.

`https://host:8888` and `http://host:8888` are one address wearing two costumes: a
bookmark, a `curl` in somebody's notes, or a browser that already knows that port will
reach for the wrong one and get a failure that looks like the server being broken. Two
numbers make the mistake impossible rather than merely recoverable, and the two settings
sit together so they read as the single decision they are.

### 3. Supply a certificate, or get a throwaway

`TLS_CERT` and `TLS_KEY` — **both or neither**, since half a pair is a misconfiguration
and minting something else instead of saying so would be the wrong kind of helpful — name
a certificate the installation already has. It is used exactly as given.

With neither set, `--tls` mints one: an elliptic-curve key on P-384, 200 days,
`CN=<instance name>`, into the gitignored `var/tls/`, under a `077` umask. The
umask is a floor rather than the key's protection: `openssl` writes the private key
`0600` on its own, so what the umask actually tightens is the *certificate* beside
it — worth keeping, and worth not mistaking for the mechanism. It is **overwritten at the next start rather than removed at boot**, because
gunicorn builds its SSL context per accepted connection and reads both files each time —
a mint into a temporary directory that cleaned up after itself would serve the first
request and fail the second.

The minted certificate is trusted by nothing and is meant to be. It carries no subject
alternative name, because nothing verifies it (§4) and a name nobody checks is a
decoration; the day something does verify it, the name is what that change buys.

### 4. The scripts never verify the certificate

Every one of them is talking to a process on this machine, over loopback, that the same
script started seconds ago and holds the pid of. Who the far end is was never in
question, and a certificate cannot answer anything that is.

What verification would add is a way for a **healthy instance to be reported as dead**:
an internal authority the machine's `curl` does not know, and `start.sh` waits out its
whole timeout and calls a serving process a failed start. That was measured rather than
imagined — the same certificate, once with the machine trusting it and once without,
gives a clean start and a spurious failure.

**This is not an exception to the rule that has no way to switch verification off.** That
rule is `little_sister.fetch`'s, and it is about reading **somebody else's** service,
where the certificate is the only thing saying whose it is. Here there is nothing it
could say that the pid does not.

### 5. Whether the machine trusts a supplied certificate is reported, not enforced

After a successful start, and only when the installation supplied the certificate,
`start.sh` asks once whether this machine can verify what is being served — and says so
when it cannot. It is exactly what a browser is about to complain about, at the moment
somebody can act on it, and it does not pretend to be the same question as *is it up*.

A minted certificate is not asked about: unverifiable by construction, so the question
would be theatre.

### 6. The readiness probe aims at `/health`

`PROBE_PATH` defaulted to `/login` — the one route that answered without a session, a
login page standing in for a liveness statement. There is one now
([ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md)), it is cheaper to
render, and it means what the probe is asking.

### 7. One checkout serves one instance, so the scripts look at both ports

The pidfile and the log are one apiece and are named after neither scheme —
`var/gunicorn.pid`, `var/gunicorn.log`. That is a **statement about how many instances a
checkout has**, and §2 did not change it: the second port exists so the two schemes
cannot be mistaken for one address, not so that a checkout can serve twice.

Looking at one port made the statement quietly false, in both directions. `./start.sh
--tls` beside a running plain instance saw nothing on `8443`, started a second gunicorn,
and truncated the log the first was still writing to — and still being *read* from,
since `fatal_in_log` and `engine_error_in_log` scan it while the new one starts. And
`./stop.sh` against a TLS instance reported "not running", then cleared that instance's
pidfile while it went on serving.

So the scripts ask **two questions, of two different sets of ports**. *Is the port I am
about to bind held by somebody else* is asked of this run's port alone — a stranger on
the other scheme's port is none of our business, because nothing here is going to bind
it. *Is this checkout already serving* is asked of both, and a start replaces what it
finds wherever it found it, which is exactly what it already did for an instance on the
same port. `our_port` in `lib.sh` is that second question, and it is the only new
concept: a port, or nothing.

An explicit `LITTLE_SISTER_PORT` collapses the two numbers into one, so there is then no
other port and nothing to look at twice.

**What "this checkout's instance" means, and why it is not the WSGI target.**
`is_ours` matched `gunicorn … <APP>`, which is precise only while every installation
serves a different target — and that is not a property anyone promised. A deployment and
the library can both serve `wsgi:app`, and two such checkouts on one port are
indistinguishable that way, so these scripts would adopt, and stop, each other's
process. Ownership is a gunicorn whose **working directory is this checkout**.

**And deliberately nothing in the command line**, which was the first answer here and
the wrong one. A command line is less a property of a process than a string that can
stop being true of it. `ps` on macOS truncates it to the terminal width — 80 columns
when the output is a pipe, which every use here is — so the tail of a gunicorn
invocation is simply absent. And gunicorn *rewrites* it to `gunicorn: master [<app>]`
when `setproctitle` is installed, which nothing in this repository installs and any
deployment may. Either one turns an argv match into a silent *not running* for an
instance that is serving perfectly, which is the worst shape a failure here can take.
The working directory survives both, is read from the live process, and identifies an
instance started from the checkout by any means rather than only by these scripts. An
unreadable one answers empty, which is not this checkout — so a process we cannot see
into is not ours, which is the safe direction.

The **pidfile's contents** were the other candidate, and carry their own version of the
problem: these scripts delete that file themselves, so identification would fail in
exactly the states they get wrong, and a pid read from a stale one is a number that may
since have been reused — macOS wraps at 99999. Its *path* is still handed to gunicorn
absolutely, so which checkout an instance belongs to stays legible in `ps` output and in
the refusals below. It just does not decide anything.

**There is a way past the refusal, and it is named where the refusal happens.** Two
checkouts on one port now refuse rather than adopt, which is the right default and the
wrong absolute: somebody who knows exactly what the other instance is should not have to
go and find its pid. `--any-instance` relaxes ownership to *any gunicorn* on the port,
and every refusal a gunicorn caused says so in the same breath. It relaxes no further —
a refusal naming a database or somebody's dev server stands, because a flag that could
stop those would cost more than the inconvenience it saves. It is a per-run flag with
**no environment variable beside it**, unlike `LITTLE_SISTER_TLS`: what makes it safe is
that a person read the refusal and answered it, and a variable exported three days ago
answers nothing.

## Consequences

- **Nothing here changes a plain run** — the same probe behavior, the same output but
  for the scheme now being named in it, and the plain port untouched *by this change*.
  Which number that is remains `instance.sh`'s business and moves for its own reasons,
  so this is a statement about what TLS costs a plain run and not a promise that the
  port never changes. The one exception is a checkout already serving under the other
  scheme, which §7 replaces rather than runs beside.
- **`openssl` becomes a requirement of a TLS start that mints**, and of nothing else: it
  is required inside that branch rather than at the top of the script.
- **These scripts are shared with the deployments that carry copies of them**, so the
  change has to reach those copies before their own checks compare them.
- **The long-open HTTPS question is settled for the server side** — gunicorn rather than
  a proxy, minted *or* supplied rather than one or the other, and trust reported rather
  than required. The client half is not: what a client that verifies has to do about a
  certificate nothing trusts is its own decision, and the macOS client is the one that
  will have to take it.
- **A deployment that wants HTTPS by default rather than per run** wraps these scripts
  or exports the environment variable; the library's default stays the simple path.
- **`--tls` on `stop.sh` is vestigial** and kept: it is accepted, and it decides only
  which port the messages call this run's and which port a stranger is refused on.
- **`./stop.sh` no longer stops an instance another checkout started**, where it would
  have once both served the same WSGI target. It refuses, names the process it found and
  names `--any-instance`, which is the deliberate way back.
- **Two checkouts still cannot both run on one port.** This makes the collision safe
  rather than absent; separating the ports is `instance.sh`'s business.

## Alternatives considered

**A setting in `instance.sh` instead of a flag.** Committed, so it is everybody's
default rather than one person's run — the wrong shape for something turned on to check
something.

**One port for both schemes.** One fewer number and a class of confusing failures kept.

**Minting only, no supplied pair.** Simpler, and it makes the person who already has a
certificate — the one with the *better* setup — the awkward case.

**Verifying the certificate in the probe.** Measured and rejected in §4: it reports a
serving instance as dead, in the exact configuration a careful deployment is most likely
to have.

**A trust-store install, so the probe and the browser both accept a minted
certificate.** A durable trusted key on somebody's machine, bought to remove a warning
that is telling the truth.

**A pidfile and a log per port**, so a checkout could genuinely serve both schemes at
once. It buys the only way to compare the two side by side, and it costs the sentence
§7 rests on: it says a checkout is a fleet, which is a larger claim than one command and
one process wants to make, and nobody has asked to run two.

**Identifying an instance by reading its pidfile.** The obvious use of a file that
already exists, and the wrong half of the idea: these scripts delete that file
themselves, so identification would fail in exactly the states they get wrong, and a pid
read from a stale file is a number that may have been recycled.

**Identifying it by the pidfile path in the command line.** Built first, and undone by
the platform: `ps` on macOS returns a truncated line, and gunicorn rewrites its own when
`setproctitle` is present. Both were found by running the suite on macOS after it was
green on Linux, where neither happens — the argument for the working directory is that
it is a fact about the process rather than a string somebody else may rewrite.

**Refusing the collision** — `./start.sh --tls` finding an instance on the plain port
and telling somebody to stop it first. Honest about the singular runtime files, and it
spends exactly the same scan as §7 to give a worse answer: once the other instance has
been found, restarting it is what `start.sh` already does for the same port.

