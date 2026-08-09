"""The deployment-supplied user list and its optional avatars (ADR-0045).

``users`` is the one configuration aspect that does not layer: the first root
declaring it wins whole (ADR-0031). It has two forms — ``config/users.yaml`` for
the list alone, or ``config/users/users.yaml`` beside ``config/users/avatars/``
once the deployment gives accounts pictures.

There is exactly one way in, and it is the path-list. A deployment that wants one
named file and no layering gives that file a configuration root of its own and names
it first in ``LITTLE_SISTER_CONFIG_DIR``: because this aspect does not merge, a
users-only root at the front already *is* a single-file override, which is why this
module has no second, file-shaped entrance.

An avatar reference is a bare file name or stem, never a path. Resolution happens
once at startup, while the selected file's bytes are read per request so replacing
that file does not need a restart.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from little_sister.config_dir import (
    CONFIG_DIR_ENV,
    YAML_SUFFIXES,
    config_roots,
    fatal,
    sole_aspect_file,
)
from little_sister.icons import ICON_TYPES
from little_sister.logger import logger

USERS_ASPECT = "users"
USERS_DOCUMENT = "users"
AVATARS_DIRECTORY = "avatars"

# Same image boundary as the link icons: a small explicit allowlist with stable
# content types, rather than platform-dependent mimetype guessing.
AVATAR_TYPES: Mapping[str, str] = ICON_TYPES

# One file name inside avatars/, with no separator or traversal. A dot may occur
# inside the name (including before an explicit extension), never at the start.
_AVATAR_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class AvatarFile:
    """One selected deployment-authored avatar and how to serve it."""

    path: Path
    content_type: str
    root: Path


@dataclass(frozen=True)
class UsersConfig:
    """The user map and the usable avatar selected for each account."""

    users: dict[str, Any]
    avatars: dict[str, AvatarFile]
    document: Path


def load_users(config_dir: str | Path | None = None) -> UsersConfig:
    """Load the user list from the configuration roots.

    The first root declaring the ``users`` aspect wins whole, in either legal form;
    a users-only root named first in the path-list is therefore how a deployment
    pins one exact file (see the module docstring).
    """
    layer = sole_aspect_file(USERS_ASPECT, config_dir)
    if layer is None:
        roots = ", ".join(str(root.resolve())
                          for root in config_roots(config_dir))
        raise FileNotFoundError(
            f"user list not found — no {USERS_ASPECT}.yaml or "
            f"{USERS_ASPECT}/ in any configuration root ({roots}). Add "
            f"config/{USERS_ASPECT}.yaml or "
            f"config/{USERS_ASPECT}/{USERS_DOCUMENT}.yaml (see "
            f"users.example.yaml), or name a root that carries one first in "
            f"{CONFIG_DIR_ENV}.")
    document = _document_in(layer)
    avatars_directory = layer / AVATARS_DIRECTORY if layer.is_dir() else None

    try:
        with open(document, encoding="utf-8") as users_file:
            body = yaml.safe_load(users_file)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"user list not found at {str(document)!r} — place "
            f"{USERS_DOCUMENT}{YAML_SUFFIXES[0]} in the {USERS_ASPECT} aspect of a "
            f"configuration root (see users.example.yaml).") from exc

    users = _user_mapping(body, document)
    avatars = _resolve_avatars(users, avatars_directory, document)
    return UsersConfig(users=users, avatars=avatars, document=document)


def read_avatar(avatar: AvatarFile) -> bytes:
    """Read a selected avatar's current bytes.

    Re-resolving against the remembered avatar root closes the gap where a selected
    file is replaced by an escaping symlink after startup. ``OSError`` and
    ``ValueError`` are deliberately allowed through: the route turns either into the
    packaged fallback.
    """
    path = _inside(avatar.root, avatar.path)
    if path is None:
        raise ValueError(f"avatar escaped its configured directory: {avatar.path}")
    return path.read_bytes()


def _document_in(layer: Path) -> Path:
    """The user document in a flat or directory-form aspect."""
    if layer.is_file():
        return layer
    found = [layer / f"{USERS_DOCUMENT}{suffix}" for suffix in YAML_SUFFIXES]
    present = [path for path in found if path.is_file()]
    if len(present) > 1:
        raise fatal(
            f"{layer}: both {' and '.join(path.name for path in present)} are "
            f"present — keep one (ADR-0045)")
    if not present:
        raise FileNotFoundError(
            f"user list not found in {str(layer)!r} — the directory-form users "
            f"aspect needs {USERS_DOCUMENT}{YAML_SUFFIXES[0]} (ADR-0045).")
    return present[0]


def _user_mapping(body: object, document: Path) -> dict[str, Any]:
    """Narrow decoded YAML to the user map the login path consumes."""
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise fatal(
            f"{document}: top-level user list must be a mapping, got "
            f"{type(body).__name__}")
    users: dict[str, Any] = {}
    for username, entry in body.items():
        if not isinstance(username, str):
            raise fatal(
                f"{document}: every login name must be a string, got "
                f"{type(username).__name__}")
        users[username] = entry
    return users


def _resolve_avatars(users: Mapping[str, Any], directory: Path | None,
                     document: Path) -> dict[str, AvatarFile]:
    """Select each configured avatar; unusable references fall back later."""
    resolved: dict[str, AvatarFile] = {}
    for username, entry in users.items():
        if not isinstance(entry, Mapping) or "avatar" not in entry:
            continue
        raw = entry.get("avatar")
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw.strip():
            _warn(username, document, f"avatar must be a non-empty file name, got "
                  f"{type(raw).__name__}")
            continue
        name = raw.strip()
        if not _AVATAR_NAME.fullmatch(name):
            _warn(username, document,
                  f"avatar {name!r} is not a bare file name")
            continue
        if directory is None:
            _warn(username, document,
                  f"avatar {name!r} needs the directory form "
                  f"config/users/users.yaml with config/users/avatars/")
            continue
        avatar = _avatar_in(directory, name, username, document)
        if avatar is not None:
            resolved[username] = avatar
    return resolved


def _avatar_in(directory: Path, name: str, username: str,
               document: Path) -> AvatarFile | None:
    """Resolve one explicit file name or extensionless stem in ``directory``."""
    if not directory.is_dir():
        _warn(username, document,
              f"avatar {name!r} has no {directory} directory to search")
        return None

    suffix = Path(name).suffix.lower()
    if suffix:
        content_type = AVATAR_TYPES.get(suffix)
        if content_type is None:
            _warn(username, document,
                  f"avatar {name!r} is not a supported image type "
                  f"({', '.join(sorted(AVATAR_TYPES))})")
            return None
        path = _inside(directory, directory / name)
        if path is None or not path.is_file():
            _warn(username, document,
                  f"avatar {name!r} was not found in {directory}")
            return None
        return AvatarFile(path=path, content_type=content_type,
                          root=directory.resolve())

    matches = [
        safe
        for entry in sorted(directory.iterdir())
        if entry.is_file() and entry.stem == name
        and entry.suffix.lower() in AVATAR_TYPES
        if (safe := _inside(directory, entry)) is not None
    ]
    if not matches:
        _warn(username, document,
              f"avatar {name!r} found no supported image in {directory}")
        return None
    if len(matches) > 1:
        _warn(username, document,
              f"avatar {name!r} is ambiguous in {directory}: "
              f"{', '.join(path.name for path in matches)} — add the extension")
        return None
    path = matches[0]
    return AvatarFile(path=path, content_type=AVATAR_TYPES[path.suffix.lower()],
                      root=directory.resolve())


def _inside(directory: Path, candidate: Path) -> Path | None:
    """The resolved candidate when it stays inside the avatar sandbox."""
    root = directory.resolve()
    resolved = candidate.resolve()
    return resolved if resolved.is_relative_to(root) else None


def _warn(username: str, document: Path, detail: str) -> None:
    """One non-fatal avatar configuration warning without any user secrets."""
    logger.warning("users: %s: user %r %s — using the default avatar (ADR-0045)",
                   document, username, detail)
