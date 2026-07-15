#!/bin/sh
# Remote host metrics for little-sister's `host-metrics` check — BUSYBOX profile.
#
# For hosts whose userland is busybox: a QNAP (QTS) NAS, an ASUS/ash router whose
# `/bin/bash` is really a symlink to busybox, and the like. Written in strict
# POSIX sh and assuming the *weakest* tools — an `awk` that can crash on a
# non-trivial program, a `df` that rejects `-P` and a path argument, integer-only
# `sleep`, and 32-bit shell arithmetic. The check pipes this to the host's `sh`
# (`sh -s`); it only MEASURES and prints `key=value` lines on stdout, while the
# OK/WARN/ERROR thresholds live in the check. For hosts with a dependable
# userland use the simpler `linux` or `macos` profile.
#
# Usage: sh host-metrics-busybox.sh [DISK_PATH] [debug]
#   DISK_PATH  filesystem to measure (default: /); `all` = every real filesystem;
#              a newline-separated list = one volume each
#   debug      if the 2nd arg is non-empty, also print debug_* diagnostic lines
#
# Emitted keys: os hostname ncpu uptime_seconds
#   disk_path disk_total_kb disk_used_kb disk_avail_kb disk_pct
#   mem_total_kb mem_used_kb mem_pct  cpu_pct  load1 load5 load15
#   (or disk{N}_* plus disk_count for a list / `all`)

disk_arg="${1:-}"
debug_flag="${2:-}"
# Disable pathname expansion: we deliberately word-split df / proc/stat fields
# with `set --` and never rely on globbing.
set -f
os="$(uname -s 2>/dev/null || echo unknown)"

echo "os=${os}"
echo "hostname=$(uname -n 2>/dev/null || echo unknown)"

# Self-guard: this profile targets a Linux-kernel busybox host. If `profile` is
# mis-set and we land on something else, emit a clear config error instead of bad
# numbers (the check renders profile_error as a visible WARN on the ssh leaf).
if [ "${os}" != "Linux" ]; then
    echo "profile_error=busybox profile expects a Linux host but uname reports '${os}' — fix 'profile' in the check config"
    exit 0
fi

# --- disk -------------------------------------------------------------------
# df columns are  Filesystem total Used Available Capacity% Mounted-on, but the
# filesystem name may contain a space; anchor on the capacity ("%") column rather
# than counting from the left, and read the mount as the fields from the first
# "/"-field after it. Try `-Pk`, then `-k`, then bare df with NO path arg (an old
# busybox rejects -P and a path argument). Parse with awk, falling back to a
# pure-shell parser only when awk produced nothing (a crash, or a real no-match —
# the fallback then agrees).
#
# IMPORTANT: the shell parser is its OWN top-level function. A `case` written
# literally inside `$( … )` makes bash 3.2 mis-parse the pattern's ")" as the end
# of the substitution; keeping it top-level avoids that trap on any host.

# awk parser — reads df output on stdin, $1 = target; prints matching rows.
_df_awk() {
    awk -v target="$1" '
        NR>1 {
            cap=0
            for (i=1; i<=NF; i++) if ($i ~ /%$/) { cap=i; break }
            if (cap < 4 || $(cap-3)+0 <= 0) next
            ms=0
            for (k=cap+1; k<=NF; k++) if ($k ~ /^\//) { ms=k; break }
            if (ms == 0) next
            mnt=$ms
            for (j=ms+1; j<=NF; j++) mnt=mnt " " $j
            pct=$cap; gsub("%","",pct)
            row=$(cap-3) " " $(cap-2) " " $(cap-1) " " pct " " mnt
            if (target == "all") {
                if ($1 !~ /^(tmpfs|devtmpfs|devfs|ramfs|proc|procfs|sysfs|cgroup|cgroup2|mqueue|overlay|overlayfs|aufs|squashfs|udev|none|nullfs|tracefs|debugfs|map)$/) print row
            } else if (target == mnt || index(target, mnt "/") == 1 || mnt == "/") {
                if (length(mnt) >= bestlen) { bestlen=length(mnt); best=row }
            }
        }
        END { if (target != "all" && bestlen > 0) print best }
    ' 2>/dev/null
}

# Pure-shell parser — same contract as _df_awk, for a host whose awk crashes.
# Sizes stay strings (a multi-TB disk would overflow 32-bit shell arithmetic).
_df_sh() {
    _target="$1"
    _best=""
    _bestlen=-1
    _hdr=1
    while IFS= read -r _line; do
        if [ "$_hdr" = 1 ]; then
            _hdr=0
            continue
        fi
        set -- $_line
        [ $# -ge 4 ] || continue
        _fs=$1
        _cap=0
        _i=0
        for _f in "$@"; do
            _i=$((_i + 1))
            case "$_f" in
                *%) _cap=$_i; break ;;
            esac
        done
        [ "$_cap" -ge 4 ] || continue
        shift $((_cap - 4))
        _total=$1
        _used=$2
        _avail=$3
        _pctf=$4
        _pct=${_pctf%[%]}
        case "$_total" in
            ''|*[!0-9]*) continue ;;
        esac
        case "$_total" in
            *[1-9]*) ;;
            *) continue ;;
        esac
        shift 4
        while [ $# -gt 0 ]; do
            case "$1" in
                /*) break ;;
                *)  shift ;;
            esac
        done
        _mnt="$*"
        [ -n "$_mnt" ] || continue
        if [ "$_target" = all ]; then
            case "$_fs" in
                tmpfs|devtmpfs|devfs|ramfs|proc|procfs|sysfs|cgroup|cgroup2|mqueue|overlay|overlayfs|aufs|squashfs|udev|none|nullfs|tracefs|debugfs|map)
                    continue ;;
            esac
            echo "$_total $_used $_avail $_pct $_mnt"
        else
            _match=0
            if [ "$_target" = "$_mnt" ] || [ "$_mnt" = "/" ]; then
                _match=1
            else
                case "$_target" in
                    "$_mnt"/*) _match=1 ;;
                esac
            fi
            if [ "$_match" = 1 ] && [ "${#_mnt}" -ge "$_bestlen" ]; then
                _bestlen=${#_mnt}
                _best="$_total $_used $_avail $_pct $_mnt"
            fi
        fi
    done
    [ "$_target" != all ] && [ -n "$_best" ] && echo "$_best"
}

# Run df once per option; parse with awk, fall back to the shell parser if awk
# produced nothing (a crash, or a genuine no-match — the fallback then agrees).
list_disks() {
    for _opt in "-Pk" "-k" ""; do
        _dfout=$(df $_opt 2>/dev/null)
        [ -n "${_dfout}" ] || continue
        _row=$(printf '%s\n' "${_dfout}" | _df_awk "$1")
        [ -n "${_row}" ] || _row=$(printf '%s\n' "${_dfout}" | _df_sh "$1")
        [ -n "${_row}" ] && { printf '%s\n' "${_row}"; return; }
    done
}

disk_path="${disk_arg}"
[ -z "${disk_path}" ] && disk_path="/"

# Number the rows arriving on stdin as disk{N}_* plus disk_count (used for "all"
# and for a list of paths); the check renders these as a "disk" branch.
emit_numbered() {
    n=0
    while IFS=' ' read -r d_total d_used d_avail d_pct d_mount; do
        [ -z "${d_mount}" ] && continue
        n=$((n + 1))
        echo "disk${n}_path=${d_mount}"
        echo "disk${n}_total_kb=${d_total}"
        echo "disk${n}_used_kb=${d_used}"
        echo "disk${n}_avail_kb=${d_avail}"
        echo "disk${n}_pct=${d_pct}"
    done
    echo "disk_count=${n}"
}

nl='
'
case "${disk_path}" in
    all)
        list_disks all | emit_numbered
        ;;
    *"${nl}"*)
        # a newline-separated list of paths → one volume each, as a branch
        printf '%s\n' "${disk_path}" | while IFS= read -r p; do
            [ -n "${p}" ] && list_disks "${p}"
        done | emit_numbered
        ;;
    *)
        # a single filesystem → a leaf (disk_* keys)
        disk_line="$(list_disks "${disk_path}")"
        if [ -n "${disk_line}" ]; then
            # POSIX here-doc (no bash here-string) so this parses under busybox
            # ash; read leaves any spaces in the mount on the last field.
            IFS=' ' read -r d_total d_used d_avail d_pct d_mount <<EOF
${disk_line}
EOF
            echo "disk_path=${d_mount}"
            echo "disk_total_kb=${d_total}"
            echo "disk_used_kb=${d_used}"
            echo "disk_avail_kb=${d_avail}"
            echo "disk_pct=${d_pct}"
        fi
        ;;
esac

# --- debug (only when asked) ------------------------------------------------
if [ -n "${debug_flag}" ]; then
    echo "debug_uname=$(uname -a 2>/dev/null | tr '\n' ' ')"
    echo "debug_disk_target=$(printf '%s' "${disk_path}" | tr '\n' ' ')"
    echo "debug_df_raw=$( { df -Pk 2>/dev/null || df -k 2>/dev/null || df 2>/dev/null; } | tr '\n' '|' | tr -s ' ')"
fi

# --- metrics (/proc) --------------------------------------------------------
# cpus — getconf/nproc may be missing (busybox); fall back to counting the
# per-core cpuN lines in /proc/stat (present on every Linux).
ncpu="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null)"
[ -n "${ncpu}" ] || ncpu="$(awk '/^cpu[0-9]/{n++} END{print n}' /proc/stat 2>/dev/null)"
[ -n "${ncpu}" ] && echo "ncpu=${ncpu}"

# uptime
[ -r /proc/uptime ] && echo "uptime_seconds=$(awk '{print int($1)}' /proc/uptime)"

# memory: used = total - available (kB)
if [ -r /proc/meminfo ]; then
    awk '
        /^MemTotal:/     {total=$2}
        /^MemAvailable:/ {avail=$2; have=1}
        /^MemFree:/      {free=$2}
        /^Buffers:/      {buffers=$2}
        /^Cached:/       {cached=$2}
        END {
            if (!have) avail=free+buffers+cached
            if (total>0) {
                used=total-avail
                printf "mem_total_kb=%d\n", total
                printf "mem_used_kb=%d\n", used
                printf "mem_pct=%.0f\n", (used*100)/total
            }
        }' /proc/meminfo
fi

# cpu: busy% across a ~1s interval from /proc/stat. Read the aggregate "cpu" line
# twice (sleep between) into ONE awk and take the delta there — that dodges two
# busybox-router traps at once: handing the huge cumulative counters back via
# `awk -v` Bus-errors that host's awk, and subtracting them in the shell
# overflows its 32-bit `$(( … ))`. awk keeps them as doubles (exact below 2^53)
# and the per-interval delta stays small. Integer `sleep` only (busybox rejects
# a fraction).
if [ -r /proc/stat ]; then
    { cat /proc/stat; sleep 1; cat /proc/stat; } | awk '
        /^cpu /{
            idle = $5 + $6
            total = 0
            for (i = 2; i <= NF; i++) total += $i
            if (seen && total > ptotal) {
                dt = total - ptotal
                di = idle - pidle
                printf "cpu_pct=%.0f\n", (100 * (dt - di)) / dt
            }
            ptotal = total; pidle = idle; seen = 1
        }'
fi

# load average
if [ -r /proc/loadavg ]; then
    read -r l1 l5 l15 _ < /proc/loadavg
    echo "load1=${l1}"; echo "load5=${l5}"; echo "load15=${l15}"
fi
