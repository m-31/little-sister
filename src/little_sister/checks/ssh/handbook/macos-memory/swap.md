# Swap

The swap space in use, from `sysctl vm.swapusage`: memory the Mac wrote to its disk to
make room. Its line adds how much swap is allocated, which macOS grows and shrinks by
itself.

## How to read it

Some swap is normal on a Mac that has run for a while: what was written out stays there
until what wrote it ends or reads it back. Much of it, or more from run to run, says the
memory is too small for what runs, and the Mac slows as it reads its memory back from
disk. It warns above 4 GiB and is an error above 8 GiB by default.

## When it grows

1. See what holds the memory: Activity Monitor's *Memory* tab, sorted by its *Memory*
   column, or `top -o mem`.
2. Restart what has grown, and quit what the Mac does not need: the swap empties as what
   wrote it ends, and a restart of the Mac empties it whole.
3. If it grows with the work the Mac is for, the Mac needs more memory, or less work.

## Its levels

`max_swap_warn` and `max_swap_error`, each a size, in the check's file, and each the
last that passes — `2 GiB` and `4 GiB` on a Mac with little memory. Write the pair
whole: a level the file leaves out is not compared. `max_swap: null` reads the swap
without grading it.
