#!/usr/bin/env bash
# Sample little-sister command check.
# Exit 0 = OK, non-zero = problem. stdout/stderr becomes the status reason.
set -euo pipefail

# Percentage used of the root filesystem (portable across macOS and Linux).
usage=$(df -P / | awk 'NR==2 { gsub("%", "", $5); print $5 }')
echo "root filesystem ${usage}% used"

# Fail (non-zero exit) when 90% or more is used.
[ "${usage:-0}" -lt 90 ]
