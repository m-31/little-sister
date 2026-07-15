"""File-freshness check: OK while a file keeps being updated."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
    coerce_code,
    config_markdown,
    parse_duration,
    plain,
    register,
)
from little_sister.status import StatusCode

DEFAULT_MAX_AGE_SECONDS = 1200   # 20 minutes


@register("file")
class FileFreshnessCheck(Check):
    """OK if the file was modified within ``max_age``; otherwise ``stale_code``.

    Use it as a heartbeat: a process that writes/touches a file regularly is
    healthy while the file stays fresh, and unhealthy once it goes stale. A
    relative ``file`` path resolves against the executing user's ``$HOME``.
    """

    def __init__(self, *, file_path: str, max_age_seconds: int,
                 stale_code: StatusCode, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.file_path = file_path
        self.max_age_seconds = max_age_seconds
        self.stale_code = stale_code

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        raw = config.get("file")
        if not raw:
            raise CheckError("file check requires a 'file' path")
        # File paths are relative to the executing user's $HOME ('~' expands too).
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = Path.home() / path
        return {
            "file_path": str(path),
            "max_age_seconds": parse_duration(
                config.get("max_age"), DEFAULT_MAX_AGE_SECONDS),
            "stale_code": coerce_code(config.get("stale_code"), StatusCode.ERROR),
        }

    def config_summary(self) -> str:
        return config_markdown({
            "file": self.file_path,
            "max age": _format_age(self.max_age_seconds),
            "stale code": self.stale_code.name.lower(),
        })

    def run(self) -> CheckResult:
        try:
            mtime = os.path.getmtime(self.file_path)
        except FileNotFoundError:
            return CheckResult(
                StatusCode.ERROR, [f"file not found: {plain(self.file_path)}"])
        except OSError as error:
            return CheckResult(StatusCode.ERROR,
                               [f"cannot read file: {plain(str(error))}"])
        age = time.time() - mtime
        if age <= self.max_age_seconds:
            return CheckResult(StatusCode.OK)
        return CheckResult(self.stale_code, [
            f"stale: last changed {_format_age(age)} ago "
            f"(max {_format_age(self.max_age_seconds)})"])


def _format_age(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    return f"{total // 3600}h{(total % 3600) // 60:02d}m"
