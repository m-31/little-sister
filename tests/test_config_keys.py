"""A type states the keys its file takes, and any other stops the start (ADR-0151).

The library takes the keys every check takes — one list, ``COMMON_KEYS``, held here to
the reader that takes them — and the keys the gradings of the check's own block are
written under; a type states its own in ``config_keys``, beside its gradings; and a key
that none of them takes, at the top level, in a ``subnodes:`` entry or in a
``children:`` block, refuses the start as the check is built, naming the file, each such
key and what its place takes. A key a type retires needs no code: it meets the same
refusal, and the library's own old spellings meet it too."""
from __future__ import annotations

import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from little_sister.checks import (
    CHECK_TYPES,
    Check,
    CheckError,
    Measurement,
    load_checks,
    register,
)
from little_sister.checks.base import COMMON_KEYS, CheckResult, _parse_common
from little_sister.status import StatusCode

#: What a `subnodes:` entry takes and what a `children:` block takes, as a refusal
#: names them (ADR-0128, ADR-0133, ADR-0139).
AN_ENTRY_TAKES = ("an entry takes: title, about, handbook, details, tags, "
                  "show_when_quiet, chips, fold_ok, reason_cap, children)")
A_BLOCK_TAKES = "it takes: chips, fold_ok, reason_cap, show_when_quiet)"


class _Recording(dict[str, Any]):
    """A configuration that remembers every key a reader looked up, in each of the
    three ways a reader looks: ``get``, ``in`` and ``[]``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.asked: set[str] = set()

    def __getitem__(self, key: str) -> Any:
        self.asked.add(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        self.asked.add(key)
        return super().get(key, default)

    def __contains__(self, key: object) -> bool:
        self.asked.add(str(key))
        return super().__contains__(key)


GRADINGS: dict[str, object] = {
    "max_depth": {"sentence": "How deep it may go.", "kind": "pair",
                  "field": "depth", "unit": "count", "warn": 3, "error": 5},
}


class _Stating(Check):
    """A type that states the keys its file takes: a value and a block it reads, and
    nothing every check takes or its gradings are written under."""

    def __init__(self, *, colour: str = "", shades: Sequence[str] = (),
                 **kwargs: Any) -> None:
        super().__init__(config_keys=("colour", "shades"), gradings=GRADINGS,
                         **kwargs)
        self.colour = colour
        self.shades = tuple(shades)

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return {"colour": str(config.get("colour", "")),
                "shades": tuple(config.get("shades") or ())}

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


def _stating(keys: object) -> type[Check]:
    """A type stating ``keys`` as they are handed, to be built in code."""
    class _Said(_Stating):
        def __init__(self, **kwargs: Any) -> None:
            Check.__init__(self, config_keys=keys,  # type: ignore[arg-type]
                           gradings=GRADINGS, **kwargs)
    return _Said


@contextmanager
def _registered() -> Iterator[None]:
    saved = dict(CHECK_TYPES)
    try:
        register("stating")(_Stating)
        yield
    finally:
        CHECK_TYPES.clear()
        CHECK_TYPES.update(saved)


def _loaded(text: str, name: str = "c.yaml") -> list[Check]:
    """The checks a configuration root holding one file, ``name``, loads."""
    with tempfile.TemporaryDirectory() as directory, _registered():
        checks = Path(directory) / "checks"
        checks.mkdir()
        (checks / name).write_text(text, encoding="utf-8")
        (checks / "s.sh").write_text("echo hi\n", encoding="utf-8")
        return load_checks(Path(directory))


def _refused(text: str, name: str = "c.yaml") -> str:
    with pytest.raises(CheckError) as caught:
        _loaded(text, name)
    return str(caught.value)


# --- every check's keys, in one list held to its reader (decision 2) ----------------


def test_every_checks_keys_are_one_list_and_it_is_what_the_reader_looks_up() -> None:
    """``COMMON_KEYS`` is every key ``_parse_common`` looks up, and ``type``, which the
    loader reads."""
    config = _Recording(path="/c")
    _parse_common(config)
    assert config.asked == set(COMMON_KEYS) - {"type"}
    assert "type" in COMMON_KEYS
    assert len(set(COMMON_KEYS)) == len(COMMON_KEYS)


def test_secrets_is_not_every_checks_but_the_type_that_reads_one() -> None:
    assert "secrets" not in COMMON_KEYS
    said = _refused("type: http\npath: /web\nurl: http://x\n"
                    "secrets: {token: env://TOKEN}\n")
    assert "unknown key(s) at the top level: secrets (http takes: " in said


# --- the top level (decisions 1 and 3) ----------------------------------------------


def test_a_typo_at_the_top_level_stops_the_start_naming_the_file_and_the_key() -> None:
    said = _refused("type: http\npath: /web\nurl: http://x\nfrequncy: 5m\n",
                    "web.yaml")
    assert said.startswith("web.yaml: unknown key(s) at the top level: frequncy (")


def test_the_refusal_names_what_the_top_level_takes_in_three_parts() -> None:
    said = _refused("type: http\npath: /web\nurl: http://x\nfrequncy: 5m\n")
    assert "(http takes: url, follow_redirects; its gradings: " in said
    assert ("; its gradings: expected_status, expected_status_reason, max_since_ok, "
            "max_since_ok_error, max_since_ok_reason, max_since_ok_warn; ") in said
    assert f"; every check: {', '.join(COMMON_KEYS)})" in said


def test_what_a_type_states_and_what_its_gradings_are_written_under_load() -> None:
    [check] = _loaded("type: stating\npath: /s\ncolour: red\nshades: [a, b]\n"
                      "max_depth_warn: 4\nmax_since_ok_error: 26h\nseries_keep: 3\n")
    assert isinstance(check, _Stating)
    assert (check.colour, check.shades) == ("red", ("a", "b"))
    assert check.config_keys == ("colour", "shades")


def test_every_key_nothing_takes_is_named_at_once_sorted() -> None:
    said = _refused("type: stating\npath: /s\nhue: red\ncolor: red\ncolour: red\n")
    assert "unknown key(s) at the top level: color, hue (stating takes: colour, " \
           "shades; its gradings: max_depth, max_depth_error, max_depth_reason, " \
           "max_depth_warn, max_since_ok, " in said


@pytest.mark.parametrize(("keys", "named"), [
    (("frequency",), "config_keys names 'frequency', which every check takes"),
    (("subnodes",), "config_keys names 'subnodes', which every check takes"),
    (("max_depth_warn",),
     "config_keys names 'max_depth_warn', which its gradings are written under"),
    (("max_since_ok",),
     "config_keys names 'max_since_ok', which its gradings are written under"),
    (("colour", ""), "config_keys holds '', which is no key's name"),
    (("colour", 3), "config_keys holds 3, which is no key's name"),
    ("colour", "config_keys must be a list of key names, not one string"),
])
def test_a_statement_of_the_wrong_kind_refuses_the_check(keys: object,
                                                         named: str) -> None:
    with pytest.raises(CheckError) as caught:
        _stating(keys)(path="/s")
    assert named in str(caught.value)


class _Silent(_Stating):
    """A type that reads a key of its own and states nothing."""

    def __init__(self, *, colour: str = "", shades: Sequence[str] = (),
                 **kwargs: Any) -> None:
        Check.__init__(self, gradings=GRADINGS, **kwargs)
        self.colour = colour


def test_a_type_that_states_nothing_takes_nothing_of_its_own() -> None:
    """Stating is required of every type (decision 5): one that states nothing has
    every key of its own refused, and the refusal says why."""
    saved = dict(CHECK_TYPES)
    try:
        register("silent")(_Silent)
        with tempfile.TemporaryDirectory() as directory:
            checks = Path(directory) / "checks"
            checks.mkdir()
            (checks / "c.yaml").write_text("type: silent\npath: /s\ncolour: red\n")
            with pytest.raises(CheckError) as caught:
                load_checks(Path(directory))
    finally:
        CHECK_TYPES.clear()
        CHECK_TYPES.update(saved)
    assert ("unknown key(s) at the top level: colour (silent takes no key of its own, "
            "stating none in config_keys; its gradings: ") in str(caught.value)


def test_name_is_a_key_no_check_takes() -> None:
    """``name`` was merged into ``path`` long ago and needs no code of its own: it is
    refused as any key nothing takes (decision 4)."""
    said = _refused("type: command\npath: /c\ncommand: 'true'\nname: c\n")
    assert "unknown key(s) at the top level: name (command takes: " in said


def test_the_check_api_epoch_is_4_and_a_type_built_for_3_refuses() -> None:
    """Stating its keys is a documented behavior every type is held to, so the epoch
    moved, and a package built for 3 refuses at import, naming both numbers."""
    from little_sister.checks import API_VERSION, require_api
    assert API_VERSION == 4
    with pytest.raises(CheckError) as caught:
        require_api(3, by="little_sister_example")
    assert "v3" in str(caught.value) and "v4" in str(caught.value)


# --- the blocks the library reads beneath the top level (decision 3) ----------------


def test_a_key_a_subnodes_entry_does_not_take_stops_the_start() -> None:
    said = _refused("type: command\npath: /c\ncommand: 'true'\n"
                    "subnodes:\n  disk: {title: Disk, chip: true}\n")
    assert said.startswith("c.yaml: unknown key(s) in subnodes.disk: chip (")
    assert f"in subnodes.disk: chip ({AN_ENTRY_TAKES}" in said


def test_a_key_a_children_block_does_not_take_stops_the_start() -> None:
    said = _refused("type: command\npath: /c\ncommand: 'true'\n"
                    "children: {flod_ok: true}\n")
    assert said == f"c.yaml: unknown key(s) in children: flod_ok ({A_BLOCK_TAKES}"
    said = _refused("type: command\npath: /c\ncommand: 'true'\n"
                    "subnodes:\n  disk: {children: {order: 1}}\n")
    assert f"in subnodes.disk.children: order ({A_BLOCK_TAKES}" in said


def test_every_place_is_named_in_one_refusal() -> None:
    said = _refused("type: command\npath: /c\ncommand: 'true'\ncommandd: x\n"
                    "children: {flod_ok: true}\n"
                    "subnodes:\n  disk: {title: Disk, chip: true}\n")
    assert said.startswith("c.yaml: unknown key(s) at the top level: commandd (")
    assert f"; in children: flod_ok ({A_BLOCK_TAKES}; in subnodes.disk: chip (" in said


# --- a retired key needs no code (decision 4) ---------------------------------------


def test_the_file_checks_old_code_key_is_refused_as_any_key_it_does_not_take() -> None:
    said = _refused("type: file\npath: /hb\nfile: /tmp/beat\nmax_age_warn: 1m\n"
                    "stale_code: WARN\n")
    assert "unknown key(s) at the top level: stale_code (file takes: file; " in said


def test_the_file_checks_old_level_is_refused_by_the_pairs_bare_key() -> None:
    said = _refused("type: file\npath: /hb\nfile: /tmp/beat\nmax_age: 20m\n")
    assert ("'max_age' accepts only null, which switches the judgment off — set a "
            "level with 'max_age_warn' or 'max_age_error'") in said


@pytest.mark.parametrize("type_name", ["host-metrics", "macos-memory",
                                       "qnap-metrics"])
def test_the_old_thresholds_block_is_refused_as_any_key_the_type_does_not_take(
        type_name: str) -> None:
    said = _refused(f"type: {type_name}\npath: /h\nhost: h\nscript: s.sh\n"
                    "thresholds: {disk: {warn: 90, error: 95}}\n")
    assert f"unknown key(s) at the top level: thresholds ({type_name} takes: " in said


@pytest.mark.parametrize(("entry", "unknown"), [
    ("{name: x, pattern: a, warn_mb: 512, error_mb: 1024}", "error_mb, warn_mb"),
    ("{name: x, pattern: a, pid: 4}", "pid"),
])
def test_a_watched_process_refuses_a_key_its_entry_does_not_take(
        entry: str, unknown: str) -> None:
    said = _refused("type: macos-memory\npath: /m\nhost: m\nscript: s.sh\n"
                    f"processes:\n  - {entry}\n")
    assert said.endswith(
        f"unknown key(s) in processes[1]: {unknown} (an entry takes: name, pattern, "
        f"max_rss, max_rss_warn, max_rss_error, max_rss_reason)")


def test_a_watched_process_takes_its_name_its_pattern_and_its_pair() -> None:
    [check] = _loaded("type: macos-memory\npath: /m\nhost: m\nscript: s.sh\n"
                      "processes:\n  - {name: x, pattern: a, max_rss_warn: 1 GiB}\n")
    assert [spec.name for spec in check.processes] == ["x"]  # type: ignore[attr-defined]


# --- the library's types state what their readers ask for (decision 5) --------------


@pytest.mark.parametrize(("type_name", "required"), [
    ("command", {"command": "true"}),
    ("file", {"file": "/tmp/beat"}),
    ("http", {"url": "http://x"}),
    ("ssh-command", {"host": "h", "command": "true"}),
    ("ssh-connect", {"host": "h"}),
    ("ssh-script", {"host": "h", "script": "s.sh"}),
    ("host-metrics", {"host": "h"}),
    ("macos-memory", {"host": "h"}),
    ("qnap-metrics", {"host": "h"}),
])
def test_what_a_library_type_states_is_what_its_reader_asks_for(
        type_name: str, required: Mapping[str, str], tmp_path: Path) -> None:
    """Every key the type's reader looks up is one it states, and every key it states
    is one its reader looks up: a stated key whose reader has gone is the one case the
    start does not refuse, so the type's own test holds it."""
    (tmp_path / "s.sh").write_text("echo hi\n", encoding="utf-8")
    config = _Recording({"type": type_name, "path": "/x", **required})
    check = CHECK_TYPES[type_name].from_config(config, tmp_path)
    asked = config.asked - set(COMMON_KEYS) - check.grading_block().keys - {"name"}
    assert check.config_keys is not None
    assert asked == set(check.config_keys)
