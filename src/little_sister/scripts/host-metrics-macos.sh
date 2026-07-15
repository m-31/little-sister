#!/usr/bin/env bash
# Remote host metrics for little-sister's `host-metrics` check — macOS profile.
#
# For macOS (Darwin): memory/cpu/load come from BSD `sysctl` / `vm_stat` / `top`
# (no /proc), disk from BSD `df`. The check pipes this to the host's `bash`
# (`bash -s`); macOS still ships bash 3.2, so this stays 3.2-clean. It only
# MEASURES and prints `key=value` lines on stdout; the OK/WARN/ERROR thresholds
# live in the check.
#
# Usage: bash host-metrics-macos.sh [DISK_PATH] [debug]
#   DISK_PATH  filesystem to measure (default: /System/Volumes/Data — the data
#              volume; macOS root "/" is a read-only system volume). `all` =
#              every real filesystem; a newline-separated list = one volume each.
#   debug      if the 2nd arg is non-empty, also print debug_* diagnostic lines
#
# Emitted keys: os hostname ncpu uptime_seconds
#   disk_path disk_total_kb disk_used_kb disk_avail_kb disk_pct
#   mem_total_kb mem_used_kb mem_pct  cpu_pct  load1 load5 load15
#   (or disk{N}_* plus disk_count for a list / `all`)

disk_arg="${1:-}"
debug_flag="${2:-}"
# Disable pathname expansion: we deliberately word-split df / loadavg fields with
# `set --` and never rely on globbing.
set -f
os="$(uname -s 2>/dev/null || echo unknown)"

echo "os=${os}"
echo "hostname=$(uname -n 2>/dev/null || echo unknown)"

# Self-guard: refuse to measure off-Darwin so a mis-set `profile` surfaces as a
# clear config error instead of garbage (the check renders profile_error as a
# visible WARN on the ssh leaf).
if [ "${os}" != "Darwin" ]; then
    echo "profile_error=macos profile expects a Darwin host but uname reports '${os}' — fix 'profile' in the check config"
    exit 0
fi

# --- disk -------------------------------------------------------------------
# Parse `df -Pk` with awk, anchoring on the capacity ("%") column so a space in
# the filesystem name (macOS autofs "map auto_home") is kept intact, and reading
# the mount from the first "/"-field after it (this also skips macOS df -k inode
# columns). 0-block stubs (an autofs map) are dropped.

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

# Run df once per option (-Pk gives POSIX 1K-block columns; -k is a fallback).
list_disks() {
    for _opt in "-Pk" "-k"; do
        _dfout=$(df $_opt 2>/dev/null)
        [ -n "${_dfout}" ] || continue
        _row=$(printf '%s\n' "${_dfout}" | _df_awk "$1")
        [ -n "${_row}" ] && { printf '%s\n' "${_row}"; return; }
    done
}

disk_path="${disk_arg}"
[ -z "${disk_path}" ] && disk_path="/System/Volumes/Data"

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
    echo "debug_df_raw=$( { df -Pk 2>/dev/null || df -k 2>/dev/null; } | tr '\n' '|' | tr -s ' ')"
fi

# --- metrics (BSD: sysctl / vm_stat / top) ----------------------------------
# cpus
ncpu="$(sysctl -n hw.ncpu 2>/dev/null)"
[ -n "${ncpu}" ] && echo "ncpu=${ncpu}"

# uptime from boot time
boot="$(sysctl -n kern.boottime 2>/dev/null | sed -n 's/.*sec = \([0-9]*\).*/\1/p')"
[ -n "${boot}" ] && echo "uptime_seconds=$(( $(date +%s) - boot ))"

# memory: (active + wired + compressed) pages vs hw.memsize
total_bytes="$(sysctl -n hw.memsize 2>/dev/null)"
if [ -n "${total_bytes}" ]; then
    vmstat="$(vm_stat 2>/dev/null)"
    pagesize="$(printf '%s\n' "${vmstat}" | sed -n 's/.*page size of \([0-9]*\) bytes.*/\1/p')"
    [ -n "${pagesize}" ] || pagesize=4096
    active="$(printf '%s\n' "${vmstat}" | awk '/Pages active/{gsub("\\.","",$3); print $3}')"
    wired="$(printf '%s\n' "${vmstat}" | awk '/Pages wired down/{gsub("\\.","",$4); print $4}')"
    compressed="$(printf '%s\n' "${vmstat}" | awk '/occupied by compressor/{gsub("\\.","",$5); print $5}')"
    used_bytes=$(( ( ${active:-0} + ${wired:-0} + ${compressed:-0} ) * pagesize ))
    echo "mem_total_kb=$(( total_bytes / 1024 ))"
    echo "mem_used_kb=$(( used_bytes / 1024 ))"
    awk -v u="${used_bytes}" -v t="${total_bytes}" 'BEGIN{ if (t>0) printf "mem_pct=%.0f\n", (u*100)/t }'
fi

# cpu: second sample of `top` (the first is a since-boot average)
cpu_line="$(top -l 2 -n 0 2>/dev/null | awk '/CPU usage/{line=$0} END{print line}')"
idle="$(printf '%s\n' "${cpu_line}" | sed -n 's/.*, \([0-9.]*\)% idle.*/\1/p')"
[ -n "${idle}" ] && awk -v idle="${idle}" 'BEGIN{ printf "cpu_pct=%.0f\n", 100-idle }'

# load average: "{ 1.20 1.10 1.05 }"
set -- $(sysctl -n vm.loadavg 2>/dev/null)
[ -n "${2:-}" ] && { echo "load1=$2"; echo "load5=$3"; echo "load15=$4"; }
