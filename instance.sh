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

# What gunicorn serves. This repository *is* the library, so it serves the library's
# own app directly. A deployment serves its `wsgi.py` instead, which registers the
# check types and extensions it installs before that app is imported.
APP="little_sister.app:app"
