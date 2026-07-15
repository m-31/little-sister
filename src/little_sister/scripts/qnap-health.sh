#!/usr/bin/env bash
# Remote QNAP hardware health for little-sister's `qnap-metrics` check.
#
# Runs on the QNAP (piped in via `ssh ... bash -s`). Uses QTS's `getsysinfo` to
# read system/CPU/drive temperatures and per-drive SMART status, printing
# `key=value` lines on stdout. Sensors the model doesn't expose (e.g. no CPU temp
# sensor) and empty drive bays are simply omitted.
#
# Usage: bash qnap-health.sh [debug]
# Emitted keys: model  sys_temp_c  cpu_temp_c  drive_count
#   drive{N}_bay  drive{N}_temp_c  drive{N}_smart

debug_flag="${1:-}"
g="$(command -v getsysinfo 2>/dev/null || echo /sbin/getsysinfo)"

# the first whole-number field of a value like "41 C/106 F" -> "41";
# empty for the "-- C/-- F" placeholder of an empty bay
celsius() { printf '%s\n' "$1" | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+$/){print $i; exit}}'; }

echo "model=$("$g" model 2>/dev/null)"

c="$(celsius "$("$g" systmp 2>/dev/null)")"; [ -n "$c" ] && echo "sys_temp_c=$c"
c="$(celsius "$("$g" cputmp 2>/dev/null)")"; [ -n "$c" ] && echo "cpu_temp_c=$c"

hdnum="$("$g" hdnum 2>/dev/null)"
case "$hdnum" in ''|*[!0-9]*) hdnum=0 ;; esac

present=0
i=1
while [ "$i" -le "$hdnum" ]; do
    status="$("$g" hdstatus "$i" 2>/dev/null)"
    smart="$("$g" hdsmart "$i" 2>/dev/null)"
    temp="$(celsius "$("$g" hdtmp "$i" 2>/dev/null)")"
    # a populated bay reports status 0 and a SMART value other than the "--" stub
    if [ "$status" = "0" ] || { [ -n "$smart" ] && [ "$smart" != "--" ]; }; then
        present=$((present + 1))
        echo "drive${present}_bay=$i"
        [ -n "$temp" ] && echo "drive${present}_temp_c=$temp"
        [ -n "$smart" ] && echo "drive${present}_smart=$smart"
    fi
    i=$((i + 1))
done
echo "drive_count=$present"

if [ -n "${debug_flag}" ]; then
    echo "debug_getsysinfo=$g"
    echo "debug_hdnum=$hdnum"
fi
