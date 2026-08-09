# ADR-0045 — User avatars live with the user-list aspect

- **Status:** Accepted
- **Date:** 2026-08-08
- **Related:** [ADR-0020](0020-user-list-location.md) (the deployment owns the user
  list), [ADR-0031](0031-deployment-config-directory.md) (aspect forms, layering and
  the explicit user-file override), [ADR-0035](0035-registering-a-config-aspect.md)
  (an aspect declares its legal forms rather than having them inferred).
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-08-06):** decision 5 keeps `LITTLE_SISTER_USERS` as an explicit file
> override, with its `avatars/` beside the named file. That override is retired by
> [ADR-0046](0046-user-list-from-the-configuration-roots.md), so the case decision 5
> covers no longer exists: avatars now only ever sit inside the aspect's directory
> form, which is where decisions 1–4 always put them. Nothing else here changes — the
> two legal forms, the bare-name reference, the fallback and the login-gated route are
> untouched, and a deployment keeping its user list outside the main tree reaches the
> same layout by giving it a configuration root of its own.

## Context

The top bar identifies the signed-in user by first name. The user list has only a
file form, `config/users.yaml`, so it has nowhere inside its aspect to carry a picture.
Putting `config/avatars/` beside that file would make `avatars` look like a separate,
unknown aspect, while embedding image data in YAML would make a small identity file
large and unpleasant to edit.

[ADR-0031](0031-deployment-config-directory.md) already reserved the answer: an aspect
may grow from one document into a directory when it needs assets beside that document.
The unresolved questions are the user-facing reference, the fallback, and whether the
configuration framework should infer this form for any aspect or the `users` loader
should declare it explicitly.

## Decision

1. **The `users` aspect accepts both forms.** A deployment may keep the flat
   `config/users.yaml` while every account uses the built-in fallback. Once it carries
   pictures, it moves the same document to `config/users/users.yaml` and puts the files
   under `config/users/avatars/`:

   ```text
   config/users/
   ├── users.yaml
   └── avatars/
       ├── jdoe.webp
       └── amorgan.svg
   ```

   Both forms in one root remain an error, and the first configuration root declaring
   the aspect still wins whole. The move changes neither layering nor authentication.

   This is **not dynamic aspect discovery**. The built-in `users` aspect declares both
   forms in the same registry where `links` does; a dependent package makes the same
   choice with `register_aspect(..., as_file=..., as_directory=...)`. A directory does
   not become meaningful merely because it exists.

2. **A user may name one avatar directly on their entry.** `avatar: jdoe` searches the
   aspect's `avatars/` directory for one supported image whose stem is `jdoe`;
   `avatar: jdoe.webp` selects that exact file. The value is a bare name, never a path:
   no `avatars/` prefix, separator, recursion or `..`. The allowed extensions and
   content types are the existing image allowlist used by link icons. Unlike links,
   there is no top-level registry: an avatar belongs to one user, so indirection buys
   nothing.

   More than one supported file matching an extensionless name is ambiguous. An
   invalid, missing or ambiguous reference is warned about and ignored; it must never
   prevent that account from logging in.

3. **No usable configured image means the packaged neutral avatar.** Omitting `avatar`
   is the ordinary case and says nothing in the log. The top-bar settings trigger shows
   the avatar beside the first name in every interactive layout; kiosk keeps omitting
   all user chrome. The image is decorative there because the adjacent name already
   identifies the user.

4. **Only the signed-in user's custom image is served.** `/user/avatar` has no username
   parameter, is login-gated, and resolves solely from the session user to the file
   selected at startup. A request argument can therefore neither enumerate accounts nor
   construct a filesystem path. The response is private, carries an ETag and uses a
   short cache so replacing the same file becomes visible without restarting.

5. **`LITTLE_SISTER_USERS` remains an explicit file override.** It still bypasses the
   configuration-root search and user layering. Its optional images live in an
   `avatars/` directory beside the named file, which keeps the avatar feature available
   to deployments that deliberately use the override without turning the override into
   a second path-list or directory-discovery mechanism.

## Consequences

- Existing deployments and user files keep working unchanged and receive the neutral
  avatar automatically.
- A deployment adding pictures performs one move, from `config/users.yaml` to
  `config/users/users.yaml`; the YAML entries themselves otherwise stay where they are.
- Avatar failures degrade only the picture, never authentication. They are visible in
  the startup log so a misspelled file does not silently look configured.
- The asset route exposes neither the user roster nor arbitrary files. Custom avatars
  remain deployment-authored, same-origin assets rather than public URLs.
- The user list is still loaded once at startup. Editing its `avatar` value or changing
  an extensionless file choice needs a restart; replacing the selected file's bytes does
  not.

## Alternatives considered

- **Infer file or directory form for every aspect at runtime.** Rejected: shape is part
  of an aspect's contract. Inference would let an accidental directory change behavior
  and would make dependent packages impossible to validate consistently.
- **Put `avatars/` beside `config/users.yaml`.** Rejected: it would be a second top-level
  aspect by the configuration-directory rules, not an asset owned by `users`.
- **Store avatar paths or URLs directly.** Rejected: paths would widen the readable
  filesystem surface, while remote URLs would leak page views and add availability to a
  decorative identity cue. A bare name inside one sandbox is sufficient.
- **Use initials as the fallback.** Rejected for now: it adds generated presentation and
  name-shaping rules when one neutral packaged image says the same thing consistently.
