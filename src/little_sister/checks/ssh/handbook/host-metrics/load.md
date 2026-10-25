# Load

The one-minute load average divided by the host's cores, so that one number reads the
same on two cores and on thirty-two — from `/proc/loadavg` on Linux, and from
`sysctl vm.loadavg` on a Mac.

## How to read it

The load counts what runs and what waits to run, and on Linux what waits for a disk or a
network filesystem too. At 1.0 a core every core is busy, and above it work queues. It
warns above 0.8 and is an error above 1.0 a core by default. A NAS, or a host that waits
on slow disks, can sit well above 1.0 and serve well.

## When it climbs

1. Busy cores, the CPU beside it high too: find the process that keeps them busy —
   `top`, or `ps aux --sort=-%cpu | head`.
2. Waiting rather than computing, the CPU low: the work waits for a disk. On Linux the
   `wa` share in the head of `top` says how much, and `iostat -x 1`, where it is
   installed, which disk.
3. If the host's normal load is above the levels, set them to it
   ([its levels](#its-levels)).

## Its levels

`max_load_warn` and `max_load_error`, a core, in the check's file, each the last value
that passes — `2.0` and `3.0` on a NAS that idles high. Write the pair whole: a level
the file leaves out is not compared. `max_load: null` reads the load without grading it.
