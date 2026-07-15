"""Serialization and auth helpers for the JSON output (backend mode).

Pure, framework-agnostic functions shared by the web layer and — later — the
satellite parser (ADR-0008). The Flask glue (content negotiation, building the
HTTP responses) stays in :mod:`little_sister.app`.
"""
from __future__ import annotations

import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from little_sister.maintenance import MaintenanceEntry
from little_sister.tree import StatusSnapshot

# Major version of the JSON / federation schema (ADR-0008). Bumped only on an
# incompatible change; additive fields keep it the same.
SCHEMA_VERSION = 1


def _utc_z(timestamp: str) -> str:
    """Render an ISO-8601 timestamp as RFC 3339 UTC with a ``Z`` suffix.

    Stored timestamps are naive server-local (ADR-0006); a naive value is taken
    to be local time and converted to UTC. An unparseable value passes through.
    """
    try:
        moment = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _maintenance_details(entry: MaintenanceEntry | None) -> dict[str, str] | None:
    """The maintenance override's details for the envelope — why / by whom / when,
    timestamps as RFC 3339 UTC — or ``None`` when the node isn't under maintenance
    (ADR-0014). The `maintenance` bool stays the quick flag beside it."""
    if entry is None:
        return None
    return {
        "reason": entry.reason,
        "set_by": entry.set_by,
        "set_at": _utc_z(entry.set_at),
        "expires_at": _utc_z(entry.expires_at),
    }


def snapshot_to_dict(snapshot: StatusSnapshot) -> dict[str, Any]:
    """Serialize a status snapshot subtree to the ADR-0008 JSON shape.

    ``own_code`` is the node's raw reported code; ``code`` is the rolled-up,
    stale-degraded effective status — a federating parent grafts ``own_code`` +
    ``children`` and re-rolls locally. The node-metadata fields (``about``,
    ``title``, ``config``) ship as **raw Markdown** — the client renders them
    (ADR-0018) — and ``maintenance_details`` carries the override's who/why/expiry.
    """
    return {
        "path": snapshot.path,
        "name": snapshot.name,
        "own_code": snapshot.own_code.name,
        "code": snapshot.code.name,
        "reasons": list(snapshot.reason),
        "timestamp": _utc_z(snapshot.timestamp),
        "description": snapshot.description,
        "frequency_seconds": snapshot.frequency_seconds,
        "about": snapshot.about,
        "title": snapshot.title,
        "config": snapshot.config,
        "maintenance": snapshot.maintenance,
        "maintenance_details": _maintenance_details(snapshot.maintenance_entry),
        "stale": snapshot.stale,
        "children": [snapshot_to_dict(child) for child in snapshot.children],
    }


def status_envelope(snapshot: StatusSnapshot,
                    now: datetime | None = None) -> dict[str, Any]:
    """Wrap a serialized snapshot in the versioned response envelope.

    ``generated_at`` is the serving instance's clock (UTC) at snapshot time.
    """
    moment = now or datetime.now(UTC)
    generated = moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": snapshot_to_dict(snapshot),
    }


def problem(status: int, title: str, detail: str | None = None) -> dict[str, Any]:
    """Build an RFC 9457 problem object (ADR-0008 / Zalando #176)."""
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    return body


def parse_api_tokens(raw: str) -> dict[str, str]:
    """Parse ``LITTLE_SISTER_API_TOKENS`` (``name=token,name2=token2``) into a
    mapping of client name to token. Empty or malformed entries are skipped.
    """
    tokens: dict[str, str] = {}
    for entry in raw.split(","):
        name, _, token = entry.partition("=")
        name, token = name.strip(), token.strip()
        if name and token:
            tokens[name] = token
    return tokens


def authenticate(auth_header: str | None,
                 tokens: Mapping[str, str]) -> str | None:
    """Return the client name for a valid ``Authorization: Bearer`` token, else
    ``None``. Tokens are compared in constant time (ADR-0008).
    """
    if not auth_header:
        return None
    scheme, _, value = auth_header.partition(" ")
    presented = value.strip()
    if scheme.lower() != "bearer" or not presented:
        return None
    for name, token in tokens.items():
        if secrets.compare_digest(presented, token):
            return name
    return None
