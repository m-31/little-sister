# Disk space

The share of a filesystem's space in use, as the host's own `df` reports it. Which
filesystem is the check's `disk_path`: by default the root filesystem, and on a Mac its
data volume, `/System/Volumes/Data`, since its root is a read-only system volume; a path
names the filesystem that holds it. With `disk_path: all`, or a list of paths, this
node is a branch with a node a filesystem, each named by the last part of its mount
point — `root` for `/` — and each with its mount point among its details.

## How to read it

The share is `df`'s own, of the space the filesystem offers its users, so one that keeps
blocks back for root can read 100% while root can still write. It warns above 80% and
is an error above 90% by default, every filesystem of the host alike; the node's
*Configuration* says the levels it was graded by.

## When it fills

1. Find what grows: `du -xh <mount> 2>/dev/null | sort -h | tail -20` on the host lists
   the largest directories of that filesystem alone.
2. The usual ones: logs that are not rotated, old backups and images, a database's
   files, a cache, a download or trash folder.
3. {error}: free some space first — writes fail on a full filesystem, and a database or
   a mail server may stop with them — and look for the cause after.
4. If the use is what the host is for, plan more space, or set the levels to what a
   share means on this filesystem ([its levels](#its-levels)).

## Its levels

`max_disk_warn` and `max_disk_error`, in the check's file, each the last share that
passes — `90%` and `95%` on a large filesystem, where a tenth is still a lot. Write the
pair whole: a level the file leaves out is not compared. They hold for every filesystem
the check reads; `max_disk: null` reads the space without grading it.
