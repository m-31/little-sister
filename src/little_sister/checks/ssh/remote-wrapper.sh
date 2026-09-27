# shellcheck shell=sh
# little-sister's remote wrapper (ADR-0089): a remote command that ends with its
# connection. It is sent as the remote command itself,
#
#     exec sh -c '<this file, without its comments>' little-sister <command>
#
# and $1 is the command, which the login shell runs the way the server would. The
# connection's stdin brings the command's script, if it has one: a line with the
# script's length in lines, 0 where there is none, and then its lines. After that,
# stdin stays open for the whole run: it is the hang-up line, which ends with the
# connection.
#
# When the connection closes, the command's group gets TERM and, two seconds later,
# KILL; at a normal end, whatever the command left behind gets the same. The only
# groups ever signaled are the one this wrapper leads and the one it gave the command.
# Where the server gave the wrapper no group of its own (Dropbear leaves a command in
# the daemon's), setsid gives the command one; where the host has no setsid either,
# only the command itself ends, and the run's stderr says so.
#
# It is sent without its comments and its indentation, and holds no single quote, so
# that the whole command line stays within the 1,024 bytes Dropbear 2012.55 takes.
c=$1
exec 3<&0 </dev/null
read -r n <&3 || exit 125
# sh's read takes a pipe a byte at a time, so nothing past the script is read.
s=
while [ "$n" -gt 0 ] && IFS= read -r l <&3; do
  s="$s$l
"
  n=$((n - 1))
done
# Whether this shell leads its group: /proc's stat where there is one, whose third
# field after the name is the group, and ps where there is not (macOS). Where neither
# answers, the wrapper takes itself to lead no group.
f=$(cat /proc/$$/stat 2>/dev/null) && f=${f##*) } || f="- - $(ps -o pgid= -p $$ 2>/dev/null)"
p() { g=$3; }
# shellcheck disable=SC2086  # one word per field
p $f
S=
t=-$$
if [ "$g" != $$ ]; then
  t=
  for S in setsid "busybox setsid" ""; do
    [ -z "$S" ] && echo "$0: no group of its own and no setsid: only the command ends with the connection" >&2 && break
    $S true </dev/null >/dev/null 2>&1 && break
  done
fi
x=${SHELL:-/bin/sh}
if [ -n "$s" ]; then
  printf %s "$s" | $S "$x" -c "$c" 3<&- &
else
  $S "$x" -c "$c" 3<&- &
fi
k=$!
[ -n "$S" ] && t=-$k
( exec >/dev/null 2>&1; cat <&3; trap "" TERM; kill -TERM $t $k; sleep 2; kill -KILL $t $k ) &
wait $k
r=$?
if [ -n "$t" ]; then
  trap "" TERM
  kill -TERM $t 2>/dev/null
  ( trap "" TERM; sleep 2; kill -KILL $t ) </dev/null >/dev/null 2>&1 3<&- &
fi
exit $r
