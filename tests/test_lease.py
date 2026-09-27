"""``little_sister.lease`` — one state directory, one writer (ADR-0090). Every lease
here is a file in a temporary directory, and the one other kernel is a string."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import textwrap
import time

import pytest

from little_sister import lease as lease_module
from little_sister.lease import Lease, LeaseRefused


def _lease(tmp_path, mark="me:1:t:a", **kwargs):
    kwargs.setdefault("kernel", "kernel-A")
    kwargs.setdefault("sleep", lambda seconds: None)
    return Lease(tmp_path / "state", mark=mark, **kwargs)


def _write_holder(tmp_path, *, mark="them:2:t:b", kernel="kernel-A", age=0.0,
                  taken="free", state="held", ttl=30.0):
    path = tmp_path / "state.lease"
    path.write_text(json.dumps({
        "mark": mark, "host": "elsewhere", "pid": 2, "kernel": kernel,
        "ttl_seconds": ttl, "taken": taken, "state": state, "claims": []}))
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def test_a_free_directory_is_taken_and_the_lease_names_its_holder(tmp_path):
    held = _lease(tmp_path)
    assert held.take() == "free"
    body = json.loads((tmp_path / "state.lease").read_text())
    assert body["mark"] == "me:1:t:a"
    assert body["kernel"] == "kernel-A"
    assert body["pid"] == os.getpid()
    assert body["ttl_seconds"] == 30.0
    assert (body["taken"], body["state"]) == ("free", "held")
    assert [claim["mark"] for claim in body["claims"]] == ["me:1:t:a"]
    held.release()


def test_the_lease_says_when_its_previous_holder_last_wrote_it(tmp_path):
    # ADR-0094: a holder rewrites the lease every beat and once more when it lets go,
    # so the file's last write before this process took it is when the previous
    # holder was last alive — the start of the gap on the instance's own node
    _write_holder(tmp_path, state="released", age=120.0)
    held = _lease(tmp_path)
    held.take()
    assert held.previous_beat is not None
    assert abs(held.previous_beat - (time.time() - 120.0)) < 5
    held.release()


def test_a_free_directory_has_no_previous_beat(tmp_path):
    held = _lease(tmp_path)
    held.take()
    assert held.previous_beat is None
    held.release()


def test_the_lease_lives_beside_the_directory_not_in_it(tmp_path):
    held = _lease(tmp_path)
    held.take()
    assert (tmp_path / "state.lease").exists()
    assert (tmp_path / "state.lock").exists()
    assert not (tmp_path / "state").exists() or not any((tmp_path / "state").iterdir())
    held.release()


def test_a_live_holder_under_this_kernel_is_refused_by_the_kernel_lock(tmp_path):
    first = _lease(tmp_path)
    first.take()
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import fcntl, os, sys, time
        fd = os.open({str(tmp_path / 'state.lock')!r}, os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        print("held", flush=True)
        time.sleep(30)
        """)], stdout=subprocess.PIPE, text=True)
    first.release()
    try:
        assert holder.stdout.readline().strip() == "held"
        second = _lease(tmp_path, mark="me:3:t:c")
        with pytest.raises(LeaseRefused) as refused:
            second.take()
        assert "under this kernel" in str(refused.value)
    finally:
        holder.kill()
        holder.wait()


def test_a_holder_under_this_kernel_that_is_gone_is_taken_over_at_once(tmp_path,
                                                                      caplog):
    _write_holder(tmp_path, kernel="kernel-A", age=1.0)
    held = _lease(tmp_path)
    with caplog.at_level(logging.INFO):
        assert held.take() == "gone"
    assert "them:2:t:b" in caplog.text
    body = json.loads((tmp_path / "state.lease").read_text())
    assert body["mark"] == "me:1:t:a" and body["taken"] == "gone"
    held.release()


def test_a_fresh_holder_under_another_kernel_is_refused_and_named(tmp_path):
    _write_holder(tmp_path, kernel="kernel-B", age=2.0)
    held = _lease(tmp_path)
    with pytest.raises(LeaseRefused) as refused:
        held.take()
    message = str(refused.value)
    assert "them:2:t:b" in message and "elsewhere" in message
    # The refused process holds nothing: a later taker under this kernel is not blocked.
    again = _lease(tmp_path, mark="me:4:t:d", kernel="kernel-B")
    assert again.take() == "gone"
    again.release()


def test_a_lapsed_holder_under_another_kernel_is_watched_for_one_beat_then_taken(
        tmp_path, caplog):
    _write_holder(tmp_path, kernel="kernel-B", age=45.0)
    slept = []
    held = _lease(tmp_path, sleep=slept.append)
    with caplog.at_level(logging.WARNING):
        assert held.take() == "lapsed"
    assert slept == [10.0]
    assert "them:2:t:b" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    held.release()


def test_a_lapsed_holder_that_beats_while_watched_keeps_the_lease(tmp_path):
    path = _write_holder(tmp_path, kernel="kernel-B", age=45.0)

    def a_beat_arrives(seconds):
        stamp = time.time()
        os.utime(path, (stamp, stamp))

    held = _lease(tmp_path, sleep=a_beat_arrives)
    with pytest.raises(LeaseRefused):
        held.take()


def test_a_released_lease_is_free_to_take(tmp_path):
    first = _lease(tmp_path)
    first.take()
    first.release()
    body = json.loads((tmp_path / "state.lease").read_text())
    assert (body["taken"], body["state"]) == ("free", "released")
    second = _lease(tmp_path, mark="me:5:t:e", kernel="kernel-B")
    assert second.take() == "released"
    body = json.loads((tmp_path / "state.lease").read_text())
    assert (body["taken"], body["state"]) == ("released", "held")
    assert [(claim["mark"], claim["taken"]) for claim in body["claims"]] == [
        ("me:5:t:e", "released"), ("me:1:t:a", "free")]
    second.release()


def test_a_lease_taken_after_a_release_and_still_beating_is_refused_to_another_kernel(
        tmp_path):
    """What a graceful restart makes, seen from the other side of a mount (ADR-0090):
    how its holder came by the lease is not whether it has let it go. A holder that
    took a released lease holds it, and another kernel meets its heartbeat."""
    first = _lease(tmp_path)
    first.take()
    first.release()
    second = _lease(tmp_path, mark="me:2:t:b")
    assert second.take() == "released"
    try:
        # Another kernel does not see this kernel's lock: the lock file it opens is a
        # file of its own.
        (tmp_path / "state.lock").unlink()
        third = _lease(tmp_path, mark="them:3:t:c", kernel="kernel-B")
        with pytest.raises(LeaseRefused) as refused:
            third.take()
        assert "me:2:t:b" in str(refused.value)
        assert second.still_ours(), "the live holder lost its lease to another kernel"
    finally:
        second.release()


def test_a_lease_that_does_not_say_it_was_released_is_held(tmp_path):
    """Only a holder's own release reads as released: a lease with no ``state`` — one
    written before the two fields were apart, whose ``how`` could mean either — is a
    holder another kernel meets by its heartbeat."""
    path = tmp_path / "state.lease"
    path.write_text(json.dumps({"mark": "them:2:t:b", "host": "elsewhere", "pid": 2,
                                "kernel": "kernel-B", "ttl_seconds": 30.0,
                                "how": "released", "claims": []}))
    with pytest.raises(LeaseRefused):
        _lease(tmp_path).take()


def test_a_holder_whose_lease_was_taken_knows_it_and_stays_lost(tmp_path):
    held = _lease(tmp_path)
    held.take()
    assert held.still_ours()
    _write_holder(tmp_path, kernel="kernel-B", mark="thief:9:t:z")
    assert not held.still_ours()
    assert held.lost is not None and "thief:9:t:z" in held.lost
    # Even if the lease came back, a holder that lost it never writes again.
    (tmp_path / "state.lease").write_text(json.dumps({"mark": "me:1:t:a"}))
    assert not held.still_ours()
    held.release()
    assert json.loads((tmp_path / "state.lease").read_text())["mark"] == "me:1:t:a"


def test_the_heartbeat_rewrites_the_lease(tmp_path):
    held = _lease(tmp_path, beat_seconds=0.05)
    held.take()
    first = os.stat(tmp_path / "state.lease").st_mtime_ns
    time.sleep(0.3)
    assert os.stat(tmp_path / "state.lease").st_mtime_ns > first
    held.release()


def test_only_four_claims_are_kept(tmp_path):
    for n in range(6):
        taker = _lease(tmp_path, mark=f"m:{n}:t:x")
        taker.take()
        taker.release()
    claims = json.loads((tmp_path / "state.lease").read_text())["claims"]
    assert [c["mark"] for c in claims] == ["m:5:t:x", "m:4:t:x", "m:3:t:x", "m:2:t:x"]


def test_the_kernel_is_named_by_its_boot_identity():
    identity = lease_module.kernel_identity()
    assert identity and ":" in identity
