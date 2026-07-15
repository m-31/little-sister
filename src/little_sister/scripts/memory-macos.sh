#!/usr/bin/env bash
# Remote macOS memory health for little-sister's `macos-memory` check.
#
# Deep memory signals beyond host-metrics' single mem_pct — the early-warning
# signs that RAM trouble is building on a small-memory Mac: the kernel's VM
# pressure level, swap in use, compressor occupancy, and per-process RSS for
# configured command-line patterns (slow leaks show as monotonic RSS growth).
# The check pipes this to the host's `bash` (`bash -s`); macOS still ships
# bash 3.2, so this stays 3.2-clean. It only MEASURES and prints `key=value`
# lines on stdout; the OK/WARN/ERROR thresholds live in the check.
#
# Usage: bash memory-macos.sh [PATTERNS] [debug]
#   PATTERNS  newline-separated substrings matched against the full command
#             line (`ps axo command`), case-sensitive; RSS (KB) is summed over
#             matching processes. The monitoring shell itself and its parent
#             carry the patterns as arguments, so those pids (and their direct
#             children, e.g. the `ps` command substitution) are excluded.
#   debug     if the 2nd arg is non-empty, also print debug_* diagnostic lines
#
# Emitted keys: os pressure_level [free_pct]
#   swap_total_mb swap_used_mb
#   mem_total_kb compressor_kb compressor_pct
#   proc_count proc{N}_pattern proc{N}_count
#   [proc{N}_rss_kb proc{N}_elapsed_seconds]

patterns_arg="${1:-}"
debug_flag="${2:-}"
# Disable pathname expansion: patterns and parsed fields must never glob.
set -f
os="$(uname -s 2>/dev/null || echo unknown)"

echo "os=${os}"

# Self-guard: refuse to measure off-Darwin so a mis-targeted config surfaces as
# a clear error instead of garbage (the check renders profile_error as WARN).
if [ "${os}" != "Darwin" ]; then
    echo "profile_error=macos-memory expects a Darwin host but uname reports '${os}' — fix the check config"
    exit 0
fi

# --- kernel VM pressure level: 1 normal, 2 warning, 4 critical ---------------
level="$(sysctl -n kern.memorystatus_vm_pressure_level 2>/dev/null)"
[ -n "${level}" ] && echo "pressure_level=${level}"

# System-wide free percentage as `memory_pressure` reports it (best effort —
# enrichment for the pressure leaf's reason, not graded).
free_pct="$(memory_pressure 2>/dev/null | sed -n 's/.*free percentage: \([0-9][0-9]*\)%.*/\1/p')"
[ -n "${free_pct}" ] && echo "free_pct=${free_pct}"

# --- swap: `vm.swapusage` = "total = 3072.00M  used = 1418.75M  free = ..." --
# The kernel formats the values in M; tolerate a K/G suffix anyway.
swap="$(sysctl -n vm.swapusage 2>/dev/null)"
if [ -n "${swap}" ]; then
    printf '%s\n' "${swap}" | awk '
        function mb(v) {
            n = v + 0
            if (v ~ /G$/) n *= 1024
            else if (v ~ /K$/) n /= 1024
            return n
        }
        {
            for (i = 1; i < NF - 1; i++) {
                if ($i == "total" && $(i+1) == "=") t = $(i+2)
                if ($i == "used"  && $(i+1) == "=") u = $(i+2)
            }
            if (t != "") printf "swap_total_mb=%.0f\n", mb(t)
            if (u != "") printf "swap_used_mb=%.0f\n", mb(u)
        }'
fi

# --- compressor occupancy vs physical RAM -------------------------------------
# Compressor exhaustion is the kernel-panic signature on a small-RAM machine;
# host-metrics folds these pages into "used" but can't see them specifically.
total_bytes="$(sysctl -n hw.memsize 2>/dev/null)"
vmstat="$(vm_stat 2>/dev/null)"
pagesize="$(printf '%s\n' "${vmstat}" | sed -n 's/.*page size of \([0-9]*\) bytes.*/\1/p')"
[ -n "${pagesize}" ] || pagesize=4096
compressed="$(printf '%s\n' "${vmstat}" | awk '/occupied by compressor/{gsub("\\.","",$5); print $5}')"
if [ -n "${total_bytes}" ] && [ -n "${compressed}" ]; then
    comp_bytes=$(( compressed * pagesize ))
    echo "mem_total_kb=$(( total_bytes / 1024 ))"
    echo "compressor_kb=$(( comp_bytes / 1024 ))"
    awk -v c="${comp_bytes}" -v t="${total_bytes}" \
        'BEGIN{ if (t > 0) printf "compressor_pct=%.0f\n", (c * 100) / t }'
fi

# --- per-process RSS for each requested pattern --------------------------------
# One ps snapshot; each pattern is a substring match on the full command line.
# Excluded from matching: this shell ($$) and its parent (their command lines
# carry the patterns as script arguments) plus their direct children (the
# command-substitution subshell that runs `ps` is a fork of $$ with the same
# argv). RSS is summed over matches so app helpers count toward their app.
if [ -n "${patterns_arg}" ]; then
    ps_out="$(ps axo pid=,ppid=,rss=,etime=,command= 2>/dev/null)"
    n=0
    while IFS= read -r pat; do
        [ -n "${pat}" ] || continue
        n=$((n + 1))
        echo "proc${n}_pattern=${pat}"
        printf '%s\n' "${ps_out}" | awk -v pat="${pat}" -v idx="${n}" \
            -v self="$$" -v parent="${PPID:-0}" '
            # etime is [[dd-]hh:]mm:ss — the oldest match reveals whether a
            # scheduled restart/recycle actually happened (uptime resets).
            function elapsed(e,    n_, d_, a_, s_) {
                d_ = 0
                n_ = split(e, a_, "-")
                if (n_ == 2) { d_ = a_[1]; e = a_[2] }
                n_ = split(e, a_, ":")
                if (n_ == 3) s_ = a_[1] * 3600 + a_[2] * 60 + a_[3]
                else if (n_ == 2) s_ = a_[1] * 60 + a_[2]
                else s_ = a_[1] + 0
                return d_ * 86400 + s_
            }
            {
                pid = $1 + 0; ppid = $2 + 0; rss = $3 + 0; et = $4
                cmd = $5
                for (i = 6; i <= NF; i++) cmd = cmd " " $i
                if (pid == self || ppid == self) next
                if (pid == parent || ppid == parent) next
                if (index(cmd, pat) > 0) {
                    total += rss; count++
                    sec = elapsed(et)
                    if (sec > oldest) oldest = sec
                }
            }
            END {
                printf "proc%d_count=%d\n", idx, count
                if (count > 0) {
                    printf "proc%d_rss_kb=%d\n", idx, total
                    printf "proc%d_elapsed_seconds=%d\n", idx, oldest
                }
            }'
    done <<EOF
${patterns_arg}
EOF
    echo "proc_count=${n}"
fi

# --- debug (only when asked) ---------------------------------------------------
if [ -n "${debug_flag}" ]; then
    echo "debug_uname=$(uname -a 2>/dev/null | tr '\n' ' ')"
    echo "debug_swap_raw=$(printf '%s' "${swap}" | tr '\n' ' ')"
    echo "debug_pagesize=${pagesize}"
    echo "debug_patterns=$(printf '%s' "${patterns_arg}" | tr '\n' '|')"
fi
