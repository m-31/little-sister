# Compressed memory

The share of the Mac's memory the compressor occupies: the pages `vm_stat` counts as
occupied by the compressor, over the memory installed — memory macOS squeezed rather
than wrote to disk. Its line adds both as sizes.

## How to read it

The compressor is how a Mac makes room before it swaps, so some of it is normal. The
kernel holds only so much compressed memory, and a compressor that fills is the
signature of a kernel panic on a Mac with little memory. It warns above 35% and is an
error above 50% of the memory by default.

## When it fills

1. See what holds the memory: Activity Monitor's *Memory* tab, which shows the
   compressed memory at its foot, or `top -o mem`.
2. Restart what holds the most, and quit what the Mac does not need.
3. {error}: do it now — past this, a small Mac stalls or panics.
4. If it fills with the work the Mac is for, the Mac needs more memory.

## Its levels

`max_compressor_warn` and `max_compressor_error`, in the check's file, each the last
share of the memory that passes. Write the pair whole: a level the file leaves out is
not compared. `max_compressor: null` reads the compressor without grading it.
