# Watched processes

The resident memory of the processes this check watches, a node an entry of its
`processes:` list: what the entry's `pattern` matches in the full command lines `ps`
lists, case and all, summed — an app's helpers count toward the app — and how long the
oldest of them has run. Each node has its pattern among its details.

## How to read it

Resident memory is what a process holds in the Mac's memory now. One that climbs from
run to run leaks, long before the pressure moves; one that drops while its oldest's time
starts again was restarted. A process that is not running is {ok} here: whether it runs
is another check's to say. It warns above 1 GiB and is an error above 2 GiB by default,
each entry alike.

## When one grows

1. Restart it — quit the app and open it again, or have its service restarted — and
   watch whether it climbs again from where it starts.
2. A climb that comes back is a leak: tell whoever owns the program, with its curve on
   the node's *Series* where the check keeps its readings.
3. If its size is what it needs, set its levels to that ([its levels](#its-levels)).

## Its levels

`max_rss_warn` and `max_rss_error`, each a size, in the process's own entry of the
`processes:` list, and each the last that passes. Write the pair whole: a level the
entry leaves out is not compared. `max_rss: null` there reads the process without
grading it.
