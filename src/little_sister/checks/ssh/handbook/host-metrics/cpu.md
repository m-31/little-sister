# CPU

How busy the processor was over about a second at each run: 100% less its idle time,
over all its cores — from `/proc/stat` on Linux, where time a core waits for a disk
counts as idle, and from `top` on a Mac.

## How to read it

Each reading is a short sample, so one high value is a moment: a backup starting, a
build. What counts is a value that stays high from run to run. It warns above 85% and is
an error above 95% by default. The load beside it says whether work is waiting.

## When it stays high

1. Find the process: `top`, or `ps aux --sort=-%cpu | head`, on Linux; `top -o cpu` on a
   Mac.
2. A process that should be idle and is not — a runaway job, a loop — restart it, and
   tell whoever owns it.
3. If the host is busy with what it is for, set the levels to what is normal for it
   ([its levels](#its-levels)), or give it more processors.

## Its levels

`max_cpu_warn` and `max_cpu_error`, in the check's file, each the last share that
passes. Write the pair whole: a level the file leaves out is not compared.
`max_cpu: null` reads the processor without grading it.
