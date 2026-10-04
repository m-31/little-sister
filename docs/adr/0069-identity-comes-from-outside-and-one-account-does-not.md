# ADR-0069 — Identity comes from outside, and never from a chain

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-08-29)
- **Related:** [ADR-0068](0068-the-login-gate-refuses-by-default.md) (the gate this sits
  on), [ADR-0023](0023-secret-references.md) (the reference the system admin's password
  is), [ADR-0064](0064-the-resolver-is-a-registration.md) (the registration this copies,
  including what a second claim on one name does),
  [ADR-0034](0034-template-slots-for-dependent-packages.md) (the seam whose failure rule
  this deliberately inverts), [ADR-0052](0052-plugin-names.md) (a name claimed once),
  [ADR-0008](0008-json-output-api.md) (the bearer token that stays out of this),
  [ADR-0100](0100-system-is-two-views.md) (the *Installed* view of `/system`, which
  shows the doors and the system-admin line)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0068](0068-the-login-gate-refuses-by-default.md) left one gate, one
`current_user()` and one `challenge()`. What is behind all three is still
`session['username']`, written by a login form comparing a plaintext password against a
list in `config/users/users.yaml`.

**That list is right for exactly one thing, and it is not the thing this is growing
into.** A personal dashboard on a developer's machine, running in fifteen seconds with
no services behind it, is the install this project protects, and a file with two logins
in it serves it perfectly. It is not a login system for a team, and the reason is not
that it is unfinished: **authentication is different in every organization**. Anything
this library built would be a guess at somebody else's directory, roles and vocabulary,
and the guess would be wrong in a way only they could see.

**Two environments are in front of us and they answer identity in structurally different
ways.** Locally, Keycloak with an authorization-code redirect: the application performs
a login. In a cloud account, a load balancer that has already completed the whole OIDC
exchange and injects a signed assertion into a header: the application performs no login
at all, and there is no flow for it to own. A contract built around *the flow* fits the
first and has nothing whatever to say about the second.

**And whatever answers can stop answering.** A monitoring application that becomes
unreachable when the identity provider is down is missing in the one hour it exists for
— and "the identity provider is down" and "something is wrong" are not independent
events.

### What everyone else does, because it decides the shape below

More than one way in is a normal thing to want — a migration between directories, a
population the directory does not cover, a way in when the directory is unreachable. The
question is not *whether* to allow it but whether the ways in are an **ordered list to
try** or **named doors**. The systems that already answered it are unanimous in an
unobvious direction.

- **Kubernetes chains and refuses to promise an order**: *"the first module to
  successfully authenticate the request short-circuits evaluation. The API server does
  not guarantee the order authenticators run in."* It can say that only because each
  authenticator keys off a different **kind** of credential, so ordering cannot decide
  anything.
- **Django chains on one axis and the order does matter**, and its own documentation
  names the consequence: *"if the same username and password is valid in multiple
  backends, Django will stop processing at the first positive match."* Two later
  additions are the tell — a `PermissionDenied` from any backend aborts the whole chain,
  which is an escape hatch invented because first-hit-wins was not expressive enough,
  and permissions become *"the superset of all permissions returned by all backends"*, so
  a backend added for one purpose grants rights through another.
- **Grafana allows several providers, one per kind, and declares the overlap out of
  scope**: *"Grafana does not support multiple identity providers resolving the same
  user. Make sure no user account overlaps between the different providers."* An
  unenforced constraint. Its documented way to reach the local form when auto-login is on
  is a separate entrance in all but name.
- **PAM is where "follow the chain until it hits" ends up**: a control vocabulary of
  `required`, `requisite`, `sufficient` and `optional`, each word added because somebody
  found a case the previous ones got wrong.
- **Keycloak's answer is that the chain belongs upstream.** Identity brokering exists so
  that *"client applications are completely decoupled from external identity
  providers"*, users *"are presented with a list of identity providers from which they
  can authenticate"*, and Keycloak *"will always issue its own token to client
  applications"*.

The common thread is that nobody who succeeded made *order* load-bearing. Kubernetes
made it irrelevant, Grafana partitioned by kind, Keycloak moved the choice in front of
the application, and Django — the one that did make order matter — documents the
ambiguity rather than solving it.

**One thing is worse here than in any of them.** A name is not only a session value in
this application: it is a **stored key**. `set_by` on a maintenance pin and an event's
authorship are held against it, and they outlive the session that produced them. Two
directories that both know `michael` corrupt data that no ordering rule can
disambiguate afterwards.

## Decision

### 1. The primitive is *who is this request*, not *the login flow*

```python
def identify(self) -> Identity | None: ...        # required
def challenge(self) -> ResponseReturnValue: ...   # required
# optional, and only because some providers have a flow at all:
def login_page(self)     -> ResponseReturnValue          # GET  /login/<door>
def submit_login(self)   -> ResponseReturnValue          # POST /login/<door>
def complete_login(self) -> ResponseReturnValue          # GET  /auth/callback/<door>
def end_session(self)    -> ResponseReturnValue | None   # GET  /logout
def enterable(self)      -> bool                         # absent means yes
```

The three providers we can name are the test of it. The **built-in** reads the session,
challenges with a redirect to its door, renders the form and signs in on submit.
**Keycloak** reads the session too, challenges with a redirect to the identity provider,
and implements the callback and an end-session redirect. The **load balancer** provider
implements `identify` and `challenge` and *nothing else* — it verifies a signed header,
and challenges with a bare `401`, because there is no flow for it to own.

That last column is the argument. A flow-shaped contract would have made the case this
deployment is actually heading for the awkward one.

**`challenge()` and `login_page()` answer different questions, and the Keycloak column is
where that matters.** The obvious reading of the list above — `challenge()` is the
redirect, `login_page()` is what a provider with a form implements — collapses them into
one answer for a redirecting provider, making `/login` the redirect too. That costs such
a deployment the only page it could have offered a choice on.

* **`challenge()` is what an unidentified request gets, and where it sends them is the
  provider's decision — this record does not make it.** The obvious answer is a
  straight redirect to the identity provider, and on an install where everybody who
  can authenticate may also use the application it is the right one: with a live
  session that redirect is *silent*, somebody clicks a dashboard link and arrives
  logged in having seen no login page at all, and a page of ours in that path would
  turn zero interactions into one on every visit, forever.

  **That reasoning assumes authenticating and being admitted are the same thing, and
  a provider that also authorizes breaks the assumption.** The first deployment to
  write one maps a directory group onto `admin` and refuses everybody outside it — so
  a redirect into the identity provider takes somebody who will *not* be admitted,
  signs them in, refuses them, and does it again on their next visit, without their
  ever clicking anything. What looked like a free redirect is a wall for exactly the
  people who most need to be told something.

  So the three shapes are all legitimate and the installation picks one. **Straight to
  the identity provider** is silent and right where authentication settles the
  question. **`prompt=none`** keeps that silence and answers the logged-out case with
  `/login` — but it does nothing for the case above, since a probe that finds a
  session sends the same person to the same refusal, faster. **Straight to `/login`**
  costs one click at the start of a browser session and gives every visitor the same
  page whatever the identity provider is doing, which is what that first deployment
  settled on. What this record fixes is only the false universal: *never render in
  this path* was advice for one shape of installation, stated as a rule for all of
  them.
* **`login_page()` is a door's own login step**, at its own address, and what somebody
  who *typed* `/login` — or was sent there by a `prompt=none` that found nobody — gets
  is a separate question the installation answers. It is never silent: somebody who
  chose this door is asking to be shown a form if that is what it takes, so a provider
  that probes in `challenge()` must not probe here, or it would bounce them back to
  the page they just left. It may be
  a page offering the choice — *sign in with the identity provider* beside *system
  administrator* (§5) — which costs nothing on the common path and, being served by us,
  renders when the identity provider is unreachable. That is the case it exists for: a
  `/login` that is only a redirect answers a broken identity provider with a browser
  error, while the other door is reachable only by somebody who remembers its address —
  `/system`'s *Installed* view at `/system/installed`
  ([ADR-0100](0100-system-is-two-views.md)), which lists it, being behind the login
  that is not working.

**The library supplies the page and the installation asks for it**, in the same
import-before-app block as the registrations it is about:

```python
identity.use("keycloak", Keycloak(), default=True, label="Company SSO")
identity.use_system_admin(reference="env://LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD")
identity.choose_at_login()
```

`/login` then renders the chooser and **`/login/<door>` is untouched**, which is the
whole of why this works. The shape we tried first — a provider returning the chooser from
its own `login_page()` — is a **loop**: both routes reach that one method, so the entry
for its own door leads back to the page it was on. Separating them also puts the choice
where it belongs, as a statement about the installation rather than about one provider,
visible on `/system/installed` beside the doors it is about. And it is a statement
rather than an inference: two enterable doors are not by themselves a request for a
menu, and working out which installations would want one is the kind of guess §3 exists
to refuse.

**A redirecting provider adds one method to appear there**: a `login_page()` returning
the redirect it was already performing. `challenge()` is not an address, so a provider
that implements only it has nothing a link can point at — and that method is what makes
`/login/keycloak` start the flow rather than dead-end.

Two smaller pieces carry it. A door prints a **label** — `name` is a path segment,
because it is a URL and a runbook entry, and *Sign in with keycloak* is not what anybody
wants; `label=` on `use()` defaults to the name, and stays the only display field for the
reason §9 gives about a claims bag. The library's own two doors bring their own words, so
no installation has to name them. And a door answers whether it **can be entered right
now**: a fifth optional method, `enterable()`, absent meaning yes, which the system-admin
account implements because its page is a `404` while its password has not resolved (§5).
One question, asked of the door, and both the chooser and the built-in login page's link
ask it — two rules about whether a way in exists is the pair that drifts and then
disagrees.

For the **load balancer** deployment this is the only thing that produces a login page at
all: implementing `identify` and `challenge` and nothing else leaves `/login` a `404`, so
there is nowhere to put the other door. Its own door is not on the page — it has no
login step, which is a fact rather than a defect — and the system admin is. A chooser
with one entry is still a page and not a redirect, because sending somebody straight
through would be the library choosing for them.

The library keeps `sign_in(Identity)` and `sign_out()`, which write the Flask session — a
provider with a login step calls them, the header provider never does. The session stays
the web-session mechanism, which is what a browser needs whatever produced the identity.

### 2. Doors, never a chain

**Several ways in are allowed. An ordered list of them to try is not.**

Each registered provider is a **door**: it has a name, a route of its own, and it is
entered deliberately. Nothing is ever "tried in turn", so there is no order to get wrong,
no first-positive-match, and no superset of anything.

```python
identity.use("local", LocalUsers(), default=True)
identity.use("keycloak", Keycloak(...), label="Company SSO")
```

`label=` is optional and defaults to the name; it is what a chooser prints (§1).

**The read path is never a chain, and one mechanism is what guarantees it.**
`sign_in()` records **which door produced the session**, and `current_user()` asks *that*
provider and no other. A header-verifying provider writes no session, so it answers for
requests that carry no door — which is unambiguous for the same reason. Adding a third
door cannot change who somebody already is.

**A door name is claimed once.** A second claim on the same name refuses at startup
naming both, the way a duplicate `type:` does
([ADR-0064](0064-the-resolver-is-a-registration.md),
[ADR-0051](0051-what-startup-refuses.md)) — because a name is how a person and a runbook
refer to a way in, and import order must not decide what it means. Registering the
**same** provider under two names is not refused and is not useful; registering two
providers under one name is the mistake this catches.

**Exactly one door is the default**, the one `/login` and `challenge()` go to when
nothing else is said. More than one `default=True` refuses at startup, for the same
reason: it is a question with one answer.

**A contradiction refuses; an omission logs.** Both refusals above are two statements
that cannot both hold, and `use()` stops the process where they happen. *No door
registered at all*, and *doors with none of them the default*, are different in kind:
nobody has said anything contradictory, somebody has not yet written a line. Refusing to
start over that would take a monitoring application down for a mistake it is able to
describe — and it would refuse the **more** usable of the two, since an instance with
doors and no default still admits anybody who knows `/login/<door>`. Both are a startup
`WARNING` from `announce_doors()` naming the line to add, on an instance that serves
`/health` (ADR-0066) and answers `401` everywhere gated.

**And a default door can stop being there, which is nobody's omission at all.** §5
closes a door whose credential did not resolve and keeps the application serving, so an
installation whose provider was the default is left with doors that work and none of
them marked — a state it did not choose, and one it cannot answer in `wsgi.py` without
writing the conditional this design exists to remove, since the door that *usually* is
the default cannot also be claimed by a second registration. What the two rules above
then cost is out of proportion to it: `challenge()` has no door to ask, so every gated
request is a `401` while `/login` is rendering a chooser listing the door that would
have let somebody in.

So **`challenge()` does not give up while there is an address of ours left**. Where the
installation asked for `choose_at_login()` and any door is registered, an unidentified
request is sent to `/login` — a page we serve, which is exactly why it still renders
when the identity provider does not. Only the **registry** decides that, never
`enterable()`: a provider is allowed to answer *can this door be entered* by probing,
and this branch runs on every unidentified request. Without the chooser, `/login` is the
default door's own step and answers `404` while there is no default, so there is
genuinely nowhere to send anybody and `401` is the honest answer rather than a shrug — as
it is for an installation that registered no door at all. Which of those two states a
refusal is in is what its message says, at `DEBUG`, because the startup `WARNING` is
where an operator is meant to read it, once. That warning says the shorter thing where
the chooser is registered: the instance is usable and only the *statement* of which door
it expects is missing.

**What this deliberately does not have.** No priority list, no fallthrough, no
`sufficient` / `requisite` vocabulary, and no rule for what happens when two doors know
the same name — because nothing ever consults two. **That last part is an operator
constraint and not a mechanism, and it is worth saying as plainly as Grafana says it**:
two directories that both know `michael` are two different people as far as a stored
`set_by` is concerned, and the library can refuse to guess but cannot make the collision
safe.

### 3. The built-in list is a provider like any other

`current_user()` goes through a registered provider, always, and the built-in is one of
them: `local_login.LocalUsers`, on the `local` door.

**Including in how it gets there — the installation registers it, like everything else it
registers.** `local_login.use_local()`, in the import-before-app block, beside the check
types and the resolvers. The library adds no door on anybody's behalf, so *can anybody log
into this instance* is answered by reading one file.

The alternative was for the library to register the list whenever a deployment had
registered none of its own, and it is worth saying why that is worse rather than merely
different, because it reads as the friendlier option. It makes the answer depend on two
conditions held in your head — no door of the deployment's own, **and** the library's own
doors not counting, so that an install with a system admin and nothing else still gets
the list — neither of them visible from the file that decides everything else about the
instance. §2 removes import order as the answer to *which provider answers*; the same
instinct removes inference as the answer to *which providers exist*. The ways in are
exactly the lines one file names.

An installation that registers nothing therefore starts, warns that nobody can sign in,
and lets nobody in — §2's omission rule, and the case it was written for. The *fifteen
seconds* install is still fifteen seconds: `setup.sh` writes the list, and the line that
registers it is in the `wsgi.py` a checkout already has.

The consequence that makes the promise true: **the `users` aspect moves behind that
provider**, read by `use_local()` and by nothing else, so a deployment using Keycloak
needs no `users.yaml` at all and never looks for one. Until this record, `load_users()`
raised `FileNotFoundError` at import when the aspect was missing, so such a deployment
could not start.

### 4. A fixed route *shape*, and still no route seam

`/login`, `/login/<door>`, `/auth/callback/<door>`, `/logout`. All owned by the library,
all dispatching to the door named in the path. **A provider never registers a route** —
the namespace is the library's and a door gets its place in it by being registered, so
this record still adds no general route mechanism.

An unimplemented hook answers **404**: it is a way in this deployment does not have, and
a redirect there risks a loop. So does a door name nothing claimed.

**`/login` is the one address that is not simply a door's**, and it is worth being exact
about it. By default it is the default door's own login step, which is what makes it the
address every install has. Under `choose_at_login()` (§1) it is a page of the library's
own instead, and then it is not a door at all: it renders on `GET` and answers `404` to a
`POST`, because a credential is taken at a door's own route and nowhere else. Either way
`/login/<door>` means the same thing, which is what lets the page link to the default
door without arriving back at itself.

### 5. One door the library ships, and it is not a provider's

**The system admin.** A door named `system-admin`, login name `admin`, its password
registered in code. It is the pattern Grafana, Keycloak and Jenkins all ship, for the
reason given in *Context*: the provider can stop answering, and that is when somebody
needs to get in.

It is **the first instance of the shape in §2 rather than an exception to it**, which is
why the shape is worth having even while there is only one provider. What makes it
special is not the mechanism but the narrowness of what it will ever do.

**A door of its own matters mechanically, not stylistically.** Under a redirect provider,
`/login` never renders a local form — when Keycloak is down there is nothing to type a
password into. `/login/system-admin` always renders a small local form when the account
is configured, and 404s when it is not.

**The built-in login page links to it**, below the form, while the account is configured
*and* its credential resolved — never to the `404` an unconfigured or unresolvable door
answers with, and never on that door's own form, which is the same document. Be precise
about what that buys, because the obvious reading is wrong: the template is rendered by
the built-in list, so the link reaches the install whose default door is a local form and
**not** the redirecting install this account mostly exists for, where `/login` renders
nothing of ours. It is a convenience for the small install. The redirecting install's
answer is the chooser in §1; until a deployment points its `login_page()` at one, the
incident path there is what it always was — a fixed address, the row on
`/system/installed`, and the runbook.

**The name is hard-coded.** A configurable one is a knob whose only effect is to make a
runbook wrong.

**The password is a registration, not a setting:**

```python
identity.use_system_admin(reference="aws-ssm-live:///little-sister/admin-password")
identity.use_system_admin(password=fetched_elsewhere)   # discouraged, and said so
```

Exactly one keyword, and **each refuses the other's shape**. `reference=` goes through
`secrets.resolve` ([ADR-0023](0023-secret-references.md)), which already refuses a string
with no scheme in the words *"a config field names a secret, it never carries one"* — so
a password hard-coded in a committed `wsgi.py` fails at startup rather than quietly
working. `password=` refuses anything shaped like `scheme://…`, because a reference
passed there would silently make the address itself the password, and that failure is
invisible until the day the door is needed.

`password=` exists because a deployment whose secret store has no little-sister resolver
would otherwise be shut out of a feature that exists for emergencies — a poor trade. It
is discouraged **operationally rather than only in prose**: which keyword was used is
logged at startup and shown on `/system/installed`, the way a deliberate resolver
replacement is recorded and shown rather than left indistinguishable
([ADR-0064](0064-the-resolver-is-a-registration.md)).

**Resolved once, eagerly, at registration.** A wrong address is then a startup warning
rather than a discovery during an incident.

**A failed resolution closes that door and the application keeps serving.** Refusing to
start would mean an unreachable parameter store takes the dashboard down during exactly
the kind of event it is watching — and if the store is unreachable, the operator cannot
read the password either. `/system/installed` says *configured but unavailable*, so an
admin who did get in can see why the other door is shut, and the startup line for a
credential that did not resolve names that view.

**No generation, ever.** A generated password has to be readable by the operator, which
means the log or a file — a live admin credential on the instance's disk, in service of a
path nobody uses, since the operator reads the parameter store. The case it would serve —
a fresh local install with nothing configured — is already served by `setup.sh` writing a
generated password into `.env`, which is a reference like any other (`env://…`).

**The comparison is `secrets.compare_digest`**, following the API tokens rather than the
built-in provider's `==`.

**What keeps this door narrow**, stated so that the next person asking has an answer: one
account, no second; a fixed name; no role beyond `admin`; no configuration for adding
another. A deployment that wants a second population wants a provider on a door of its
own, which §2 already gives it.

**It is visible while it is in use.** A distinct packaged avatar, so every page says which
door you came through — a session left open for a week after the incident is the real
risk, and this is the cheapest thing that prevents it. A `WARNING` on every system-admin
login, because it is an event somebody should be able to reconstruct afterwards. A line
on `/system/installed`. Deliberately **no page banner**: three channels is enough, and
the fourth would be shouting.

**`set_by` records the name only.** It is a stored key that maintenance pins are held
against, so putting *which door somebody came through* into it would leak a mechanism
detail into data that outlives the mechanism. The door is
`identity.session_door()`, reading the marker `sign_in()` wrote, with
`is_system_admin_session()` as the named convenience over it — which also keeps
`Identity` at four fields, since how you got in is a property of the session rather than
of the person.

### 6. Every door is visible on `/system/installed`

`/system/installed` already answers *what is installed and what did it contribute* —
the check-type roster, the package inventory, the extension seams, the assembled policy.
Identity joins it, because a way into an application is exactly the kind of thing that
must not be knowable only by reading the source.

One row per door: its **name** (with its **label** beside it where they differ), its
**route**, the **provider** behind it, the **package** that registered it (inferred from
the call site, as a resolver's is) and which one is the **default**. A line beneath says
what **`/login` itself** does — the default door's login step, or a choice of these doors
— which no row can say and which is part of the way in. The system-admin row says whether
it is configured, whether its credential resolved, and **which keyword configured it** —
so a deployment that took the discouraged shortcut can be seen to have taken it by
somebody who is not reading `wsgi.py`.

A seam nobody can see from the running instance is indistinguishable from one that
silently did not take ([ADR-0064](0064-the-resolver-is-a-registration.md)), and that goes
double for the doors.

### 7. A provider that raises fails closed, unlike the seam next door

[ADR-0034](0034-template-slots-for-dependent-packages.md) contains a broken slot filler
on the principle that monitoring must not go dark because a button broke. Applying the
same instinct here would be a hole: an `identify()` that raises is treated as **no
identity**, logged, and never as *let them through*. Containment is right for a
decoration and wrong for a gate, and the two sit close enough together that the
difference is worth writing down.

A failing provider takes down **its own door and no other**, which is the whole reason
the doors are separate — and that has to hold for every hook, not only `identify()`.
Two of them are asked at exactly the moment the thing behind them has stopped
answering, and both were unguarded until a review found them:

- **`enterable()`** invites *can this door take a credential right now*, which a
  provider may well answer by probing the identity provider. Raising there took down
  the whole chooser — every other door with it — which is precisely the promise above,
  broken on the morning the page exists for. A raising hook means **not enterable**,
  logged, and that door alone is left off the page.
- **`end_session()`** builds a goodbye out of whatever the provider knows about the
  identity provider, and building it can throw. Unguarded that made `/logout` a `500`
  **with the session still open** — the quiet failure, since an error page looks the
  same either way. The provider's goodbye is best-effort and logged; clearing the
  local session is not optional and happens regardless. *Logging out has to work
  whatever the provider does* has to include *fails*.

### 8. `identify()` is answered once per request

The gate calls it, a view calls it again through `signed_in()`, and the avatar context
processor calls it a third time. For the built-in that is three session reads; for a
header-verifying provider it is three signature checks. Cached in `flask.g` for the
request.

### 9. `Identity` stays four fields

`name`, `firstname`, `lastname`, `admin`. No raw-claims bag: a deployment that needs more
already has it, in its own provider code, and a claims dictionary on the library's type
is a surface owed forever for a convenience nobody asked for.

## Consequences

- **Every installation names its doors, and one that names none lets nobody in.** That is
  the breaking half of this record for a deployment that supplied no provider of its own:
  it needs a `local_login.use_local()` line, or it starts, warns, and answers `401`
  everywhere gated. The compensation is that the question *who can log in here* is
  answered by one file rather than by a rule about what the library would infer.
- **little-sister gains a `wsgi.py` of its own**, tracked rather than generated, and
  `instance.sh` serves `wsgi:app`. It registers both of this installation's doors — the
  login list and the system admin. It is the shape every deployment already has, and this
  repository stops being the one installation that does not do what its own documentation
  describes. `mypy`'s target list gains it — a `files = ["src"]` would type-check
  everything except the one file that carries the registration order.
- **`setup.sh` changes what it writes.** The generated login becomes `viewer`, **not** an
  admin, keeping `change-me` because that password is meant to be *edited*; and `.env`
  gains a generated system-admin password, because that one is meant to be *read*. After
  a fresh setup the powerful account is the one with real entropy and the everyday one is
  the weak editable placeholder, which is the right way round.
- **A migration between directories is possible without a priority list**: the old door
  and the new one both stand, each entered deliberately, until the old one is
  unregistered. What the library still cannot do is tell two people with one name apart,
  and it says so rather than pretending.
- **A deployment can be locked out of its own admin actions** if it registers no system
  admin and no door maps anybody to `admin`. That is the deployment's decision to make;
  the library's job is to make a door available, not to insist on it.
- **`/user/avatar` degrades correctly** under a provider that is not the built-in: the
  avatar map belongs to the `users` aspect, so it is empty and every viewer gets the
  packaged neutral image. Nothing to change, and worth saying so before somebody fixes it.
- **`little_sister.identity` joins the promised surface** (§11) with `Identity`, `use`,
  `use_system_admin`, `sign_in` / `sign_out`, `session_door` and the provider protocol,
  and `little_sister.local_login` with `use_local`.
  The check-authoring epoch does **not** move: that epoch exists because check types are
  third-party and numerous, while a provider lives in a deployment's own code or in a
  package that pins the library, so ordinary semver carries it.
- **The JSON API is untouched.** Its bearer tokens authenticate machines, and whether an
  identity provider should also issue them is a separate and still-unsettled question
  rather than a consequence of this one.
- **The documentation owes a page nobody can infer from the code**: an install can have
  several doors now, which ones it has is its own choice, and after `setup.sh` the only
  admin is behind the system-admin door.

## Alternatives considered

**An ordered chain of providers, first hit wins.** The obvious generalization, and the
one the systems in *Context* either avoided or documented their way around. It makes
*who you are* depend on registration order in the one part of the application where a
silent disagreement is a breach rather than a bug; it needs an escape vocabulary the
moment somebody wants "this one must pass" (Django grew one, PAM grew four); and here it
would resolve a name against whichever directory happened to be listed first, into a
field that pins and events are stored against. Doors give the same reach with the
ordering removed rather than defended.

**One provider, full stop.** What this record said in draft. It answers the resilience
case with the system-admin door and answers the migration case not at all, and the rule
would be superseded by the first cutover. The line that actually matters is *no ordered
fallback*, not *no second way in*.

**Partitioning by credential kind** — one provider per session, header, token — which is
what Kubernetes and Grafana effectively do. It makes ordering irrelevant, and it does not
serve the case most likely to arrive: two directories that are both session-shaped,
during a migration.

**Generating the system-admin password when none is configured.** Requires putting a live
admin credential where the operator can read it — the log, or a file — for a path nobody
in the intended workflow uses.

**Falling back to the system-admin door when nothing claims the default.** The other way
to answer the closed-default case in §2, and the more tempting one, since it needs no new
behavior anywhere. It is the inference §3 refuses, and the damage is wider than the
sentence suggests: `default_door()` is also what the read path asks for a request
carrying no door, and what the bare `/login` renders, so an installation that registered
that account only as an emergency entrance would silently acquire it as its way in — and
`announce_doors()` would report it as the default at startup. Redirecting to a page the
installation already asked for infers nothing.

**`use_system_admin(default=True)`.** The same case answered in the deployment instead,
and it cannot be written unconditionally: the door that usually *is* the default would
then be a second claim, which §2 refuses, so the line would have to read
`default=<the other door> is None` — the conditional in somebody's `wsgi.py` that this
area is trying to remove.

**A configurable system-admin login name.** A knob whose only effect is that the runbook
and the instance can disagree.

**A general route-registration seam, so a provider brings its own.** A route here is not
an isolated thing: it has to say who gates it, what it may put on a page, what it does
about content negotiation, and how its name avoids colliding with one we add later. A
door namespace the library owns costs none of that, and it is the prototype the general
seam would be generalized from if a second, non-authentication caller ever appears.

