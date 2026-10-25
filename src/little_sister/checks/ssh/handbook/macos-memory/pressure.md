# Memory pressure

The kernel's memory-pressure level, from `sysctl kern.memorystatus_vm_pressure_level`:
1 normal, 2 warning, 4 critical. Its line adds the share of the memory free across the
system, as `memory_pressure` reports it.

## How to read it

The level is the kernel's own judgment of how short of memory the Mac is, and it moves
before the Mac slows: at a warning it compresses and swaps harder, and at critical it
presses apps to give memory back and may end some — on a Mac with little memory, the
step before a stall or a panic. By default a normal level passes, a warning warns and a
critical level is an error.

## When it rises

1. See what holds the memory: Activity Monitor's *Memory* tab, sorted by its *Memory*
   column, or `top -o mem` over SSH.
2. Quit what the Mac does not need, and restart what has grown — an app that leaks, a
   browser with many tabs. Where the check watches processes, their nodes say which of
   them grew.
3. {error}: do it now, before the Mac stalls or ends apps itself.
4. If it rises with the work the Mac is for, the Mac needs more memory than it has.

## Its levels

`max_pressure_warn` and `max_pressure_error`, in the check's file, each the last level
that passes — `1` and `2` by default. Write the pair whole: a level the file leaves out
is not compared. `max_pressure: null` reads the level without grading it.
