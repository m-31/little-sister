# Memory

The share of the host's memory in use. On Linux it is the memory less what the kernel
counts as available, from `/proc/meminfo`, so that the caches it would drop for a
program count as free; on a Mac, the active, wired and compressed pages over the memory
installed, from `vm_stat` and `sysctl hw.memsize`.

## How to read it

A high share is no trouble by itself while the host serves well: Linux keeps what it can
in its caches, and a Mac compresses before it swaps. It warns above 85% and is an error
above 95% by default, and a share that climbs from run to run says more than one reading
does. On a Mac, `macos-memory` reads the pressure, the swap and the compressor, which
say more than one share can.

## When it fills

1. See what holds it: `ps aux --sort=-rss | head` on Linux, `top -o mem` on a Mac.
2. A process that grows from run to run leaks: restart it, and tell whoever owns it.
3. {error}: a Linux host that runs out ends a process — its OOM killer, whose work
   `dmesg` shows — and a Mac starts to stall. Restart what holds the most before the
   kernel chooses.
4. If the use is what the host is for, give it more memory, or set the levels to it
   ([its levels](#its-levels)).

## Its levels

`max_memory_warn` and `max_memory_error`, in the check's file, each the last share that
passes. Write the pair whole: a level the file leaves out is not compared.
`max_memory: null` reads the memory without grading it.
