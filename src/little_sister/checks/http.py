"""HTTP(S) health check."""
from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
    config_markdown,
    plain,
    register,
)
from little_sister.status import StatusCode


@register("http")
class HttpCheck(Check):
    """GET a URL; OK when the response status is one of ``expected_status``."""

    def __init__(self, *, url: str, expected_status: set[int],
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.expected_status = expected_status

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        url = config.get("url")
        if not url:
            raise CheckError("http check requires a 'url'")
        expected = config.get("expected_status", 200)
        if isinstance(expected, int):
            expected = [expected]
        return {"url": str(url), "expected_status": {int(s) for s in expected}}

    def config_summary(self) -> str:
        expected = ", ".join(str(s) for s in sorted(self.expected_status))
        return config_markdown({"url": self.url, "expected status": expected})

    def run(self) -> CheckResult:
        try:
            request = urllib.request.Request(self.url, method="GET")
            # URL is operator-configured (trusted).
            with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception as error:  # any transport failure is an ERROR
            return CheckResult(StatusCode.ERROR,
                               [f"request failed: {plain(str(error))}"])
        if status in self.expected_status:
            return CheckResult(StatusCode.OK)
        expected = ", ".join(str(s) for s in sorted(self.expected_status))
        return CheckResult(
            StatusCode.ERROR, [f"HTTP {status} (expected {expected})"])
