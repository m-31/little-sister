"""The golden envelope — one artifact every repository in the family tests against.

`docs/api/openapi.yaml` is normative and says what the envelope *may* contain; this
is one envelope that actually contains it, produced by this application's own API
and held to it by `tests/test_contract_fixture.py`. A client that decodes this file
decodes every optional shape `schema_version` 2 has: a node with and without a
`run`, a run on a schedule carrying `frequency_seconds` and `stale_after_seconds` and
one carrying neither, entries addressable and prose, an entry carrying `subject` and
`data`, one carrying neither and one whose record was `refused`, a record with the typed
``at`` / ``started`` / ``ended`` keys at two depths, a `maintenance` pin and a null, the
envelope's own `instance` block, and **both** shapes of `contribution` — the pin's,
which withholds and reports a null code, and a damped node's, which transforms: the node
reads ERROR, the parent counted OK, and `contribution.code` is that OK.

**A field added to the envelope makes this artifact stale in the same change.** ADR-0080
decision 1 says a field added to the snapshot is added to the contract in that change;
this is the other half of it. ``python tests/test_contract_fixture.py`` rewrites the
artifact and the diff is the review — not a follow-up, or the next person meets it as a
red gate and has to work out why.

**It ships in the wheel** so a plugin's test suite can read it without vendoring a
copy, and it is a shared file of the family (`release/family.toml`) so the macOS
client carries the identical bytes under `apple/`. Two repositories testing two
hand-written fixtures is the drift this exists to end.

Some field *names* are volatile — they differ between two correct runs — and the
artifact names them itself under ``volatile`` so a consumer in another language does
not have to keep its own list: ``generated_at``, ``observed_at`` and ``next_at``, the
instance's ``version``, and a pin's ``set_at`` and ``created_at``. Everywhere they
occur the artifact holds a fixed placeholder and a comparison normalizes them. A pin's
``expires_at`` is **not** among them: the scene fixes it, so it is a real value a
client's date decoding is tested against.
"""
from __future__ import annotations

import json
from importlib import resources
from typing import Any

__all__ = ["ARTIFACT", "golden_artifact", "golden_envelope", "normalize"]

#: The artifact's file name inside this package.
ARTIFACT = "envelope-2.json"


def golden_artifact() -> dict[str, Any]:
    """The whole artifact: ``schema_version``, ``volatile`` and ``envelope``."""
    text = resources.files(__name__).joinpath(ARTIFACT).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def golden_envelope() -> dict[str, Any]:
    """Just the envelope, as `GET /status` answers it."""
    envelope: dict[str, Any] = golden_artifact()["envelope"]
    return envelope


def normalize(value: Any, volatile: list[str]) -> Any:
    """``value`` with every field named in ``volatile`` replaced by a placeholder.

    Applied to both sides of a comparison, so what is compared is the shape and
    every stable value, and never the clock or the version this build happens to
    carry. Recursive by field **name** rather than by path, because the same field
    appears on every node and a path list would be a second thing to keep in step.
    """
    if isinstance(value, dict):
        return {key: ("<volatile>" if key in volatile and value[key] is not None
                      else normalize(value[key], volatile))
                for key in value}
    if isinstance(value, list):
        return [normalize(item, volatile) for item in value]
    return value
