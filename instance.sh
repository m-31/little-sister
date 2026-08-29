# shellcheck shell=bash
# shellcheck disable=SC2034  # both values are used by lib.sh and the run scripts
#
# What this instance is, for the run scripts. **This is the only file among them that
# differs between the three installations** — `setup.sh`, `start.sh`, `stop.sh`,
# `lib.sh` and `test_api.sh` are byte-identical and compared against each other on
# every commit (`release/family.toml`). Anything that is true of one installation and
# not the others belongs here rather than in a fourth wording of a shared script.

# What the scripts call this instance in the lines an operator reads.
NAME="little-sister"

# What port this instance serves on. The family default — shared with the other
# installations rather than reserved from them, which is now safe rather than merely
# tidy: a second checkout on this number is **refused** by `start.sh` and `stop.sh`
# rather than adopted, so two of them never quietly
# restart or stop each other. Running two at once is what `LITTLE_SISTER_PORT` is for.
PORT=8888

# And where `./start.sh --tls` serves instead. The scheme and the port move together,
# so the two numbers are one decision and are read side by side.
TLS_PORT=8443

# What gunicorn serves. Every installation in this family serves its own `wsgi.py`,
# which registers what it adds before `little_sister.app` is imported — and this one
# is an installation too: it registers no check types, but it does register the
# system-admin account, and a registration after the app
# import is a registration that came too late.
APP="wsgi:app"
