# SSH

The connection the check reads the host through: one SSH session a run, which pipes a
metrics script to the host's shell and reads what it prints. It is no resource of the
host. While it fails, the host's other leaves are not read.

## What it says

- {ok}: the host answered, and the script ran.
- {warn}: ssh printed an advisory beside a working connection — most often that its key
  exchange is not post-quantum — or the host is not of the kind the check's `profile`
  names, which its line says.
- {error}: the connection failed, or the script printed no metrics.

## When it fails

1. Try the connection from the machine the monitor runs on, as the user it runs as,
   with the check's `user`, `port` and `identity_file` where it sets them:
   `ssh -o BatchMode=yes <host> true`. A password prompt, a question about the host's
   key or a timeout is what the check meets too, and it answers none of them.
2. A host key that changed: make sure the new key is the host's, then remove the old
   one with `ssh-keygen -R <host>` and connect once by hand to accept the new one.
3. A connection refused or timed out: is the host up, and does its firewall let the
   monitor in on its SSH port?
4. Connected, but no metrics: the line says what the host printed instead.
   `debug: true` in the check's file adds what ssh printed to this leaf's lines.

## When it warns

A host that cannot offer a post-quantum key exchange, an old Dropbear among them, has
ssh say so on every connection. Update the host where you can; where you cannot, the
check's file takes the advisory back: `options: ["-o", "WarnWeakCrypto=no-pq-kex"]`.

A `profile` that does not fit the host — `linux` on a busybox NAS, `macos` on a Linux
box — is named as such: set it to the host's kind, `linux`, `macos` or `busybox`.
