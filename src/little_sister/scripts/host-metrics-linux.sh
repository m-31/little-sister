#!/usr/bin/env bash
# Remote host metrics for little-sister's `host-metrics` check — LINUX profile.
#
# For mainstream Linux with a dependable GNU/BusyBox-free userland (Debian,
# Ubuntu, CentOS/RHEL, …): /proc is present and `awk` + `df -P` work. The check
# pipes this to the host's `bash` (`bash -s`). It only MEASURES and prints
# `key=value` lines on stdout; the OK/WARN/ERROR thresholds live in the check.
# Hosts whose userland is busybox (a QNAP, an ASUS/ash router) want the
# `busybox` profile instead, which carries pure-shell fallbacks; macOS wants the
# `macos` profile.
#
# Usage: bash host-metrics-linux.sh [DISK_PATH] [debug]
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
# Disable pathname expansion: we deliberately word-split df fields with `set --`
# and never rely on globbing.
set -f
os="$(uname -s 2>/dev/null || echo unknown)"

echo "os=${os}"
echo "hostname=$(uname -n 2>/dev/null || echo unknown)"

# Self-guard: refuse to measure off-Linux so a mis-set `profile` surfaces as a
# clear config error instead of garbage (the check renders profile_error as a
# visible WARN on the ssh leaf).
if [ "${os}" != "Linux" ]; then
    echo "profile_error=linux profile expects a Linux host but uname reports '${os}' — fix 'profile' in the check config"
    exit 0
fi

# Same hard guard for the *other* easy mistake — this (linux) profile on a busybox
# host, where awk can crash and `df -P` is rejected. busybox `df` self-identifies
# in `--help` ("BusyBox v… multi-call binary") while GNU/BSD df don't, so this is
# reliable even on an old router whose `readlink -f` isn't. Refuse and point at the
# busybox profile, exactly as the uname guard above does for the wrong OS.
case "$(df --help 2>&1)" in
    *BusyBox*)
        echo "profile_error=linux profile expects a full (non-busybox) userland but this host's df is busybox — set 'profile: busybox' in the check config"
        exit 0 ;;
esac

# --- disk -------------------------------------------------------------------
# Parse df with awk, anchoring on the capacity ("%") column (so a space in the
# filesystem name is fine) and reading the mount from the first "/"-field after
# it. This profile trusts a working awk and `df -P`; the busybox profile keeps a
# pure-shell fallback for hosts whose awk crashes.

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

# Run df once per option (coreutils takes -Pk; -k is a fallback) and parse it.
list_disks() {
    for _opt in "-Pk" "-k"; do
        _dfout=$(df $_opt 2>/dev/null)
        [ -n "${_dfout}" ] || continue
        _row=$(printf '%s\n' "${_dfout}" | _df_awk "$1")
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

# --- metrics (/proc) --------------------------------------------------------
# cpus
ncpu="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null)"
[ -n "${ncpu}" ] || ncpu="$(awk '/^cpu[0-9]/{n++} END{print n}' /proc/stat 2>/dev/null)"
[ -n "${ncpu}" ] && echo "ncpu=${ncpu}"

# uptime
[ -r /proc/uptime ] && echo "uptime_seconds=$(awk '{print int($1)}' /proc/uptime)"

# memory: used = total - available (kB); MemAvailable is absent on old kernels
# (e.g. CentOS 6), so fall back to free+buffers+cached there.
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

# cpu: busy% across a ~1s interval from /proc/stat (delta taken inside one awk).
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
