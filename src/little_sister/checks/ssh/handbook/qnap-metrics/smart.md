# SMART

Each drive's SMART verdict — the NAS's word for what the drive reports about its own
health — as QTS's `getsysinfo` gives it: a node a populated bay, with its bay among its
details.

## How to read it

`GOOD`, `OK`, `PASSED` or `NORMAL` is {ok}, `Warning` is {warn}, and any other word is
{error}, so that a word nobody named is never quieter than a failing drive. A warning
says the drive reports trouble while it still works; the NAS's storage pages show which
of its attributes moved.

## When a drive fails

1. Make sure the backup is current before anything else.
2. {warn}: order a replacement — the same size or larger, of the kind the NAS takes —
   and plan the swap.
3. {error}: replace the drive now. Where its volume keeps a second copy of the data, a
   RAID 1, 5, 6 or 10, the NAS rebuilds it onto the new drive, and the volume is at risk
   until the rebuild ends; where it keeps none, the backup is the copy.
4. Replace it as the NAS's manual says for the model; the bay is among the drive's
   details.
5. Watch the rebuild to its end, and the other drives' verdicts with it: a second drive
   that warns during a rebuild is the moment the backup is for.

## Its sentence

The check's file can give the verdict a sentence of its own, which its line says where
it fires — whom to call, where the spares are: `smart_reason`.
