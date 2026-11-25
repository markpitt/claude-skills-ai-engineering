# Establishing what stopped the work

The cause decides what can be recovered. A clean reboot leaves files and git intact. A power loss can
leave half-written files and an orphaned lock. A full disk can leave a truncated file with no error at
all. Establish the cause from evidence before the inventory, because it tells you what to look for.

## Contents

- The four usual causes
- Reading the boot history
- Clean stop or crash
- Out of memory
- Disk full, in the guest and on the host
- WSL2 restarts and Windows-side reboots
- Recording what could not be established

## The four usual causes

| Cause | What it leaves behind | What to look for first |
|---|---|---|
| Clean reboot (Windows update, user restart) | Files and git intact. Processes gone. Terminal sessions gone. | Shutdown sequence in the previous boot; a reboot reason on the Windows side |
| Crash or power loss | Half-written files, stale git locks, a truncated log | Previous boot's log ends abruptly; no shutdown targets reached |
| Out of memory kill | One process killed, possibly mid-write | Kernel log lines naming a killed process |
| Disk full | Truncated writes, failed commits, unlogged failures | `df` on the guest and on the host drive that holds the virtual disk |

A single event can be more than one of these. Disk full often causes a crash, and a crash leaves the
disk-full writes half done. Check both.

## Reading the boot history

```sh
uptime -s                                              # boot time of the current kernel
cat /proc/uptime                                       # seconds since that boot
journalctl --list-boots --no-pager                     # boot IDs and offsets, if the journal persists
```

- `journalctl --list-boots` lists `-1`, `-2` and so on only when the journal is persistent. A host with
  only the current boot listed has a volatile journal, and nothing before this boot can be read.
- To read the previous boot: `journalctl -b -1 --no-pager | tail -n 200`. Read the last lines first.
- If `-b -1` gives "No entries", it is not an empty log. It means the journal did not keep that boot.
  Report that the cause could not be established from the journal.

## Clean stop or crash

Read the last 200 lines of the previous boot. A clean stop has the service manager stopping units in
order, reaching the shutdown target, and then the machine powering off or restarting. A crash stops
mid-stream: the last entries are ordinary activity, with no shutdown sequence after them.

```sh
journalctl -b -1 --no-pager | tail -n 200
journalctl --user -b -1 -u <user-unit> --no-pager | tail -n 40   # a user unit the work depended on
```

Substitute the units the work depended on. User units log to the user's journal, so use `--user`. A user
unit that logs its own stop is evidence of a clean stop for that unit even when the machine crashed later.

## Out of memory

```sh
journalctl -k -b -1 --no-pager | grep -i -E 'out of memory|oom-kill|killed process'; echo "grep exit $?"
```

- A kill line names the process and its memory use. Note the process name, not its command line.
- An OOM kill of an agent's process means its last step may be partial. Treat that step as unverified.
- Exit 1 from grep means no kill was logged. If the journal is volatile, that is no proof of no kill.

## Disk full, in the guest and on the host

Inside the guest:

```sh
df -h /        ; echo "df exit $?"
df -i /        ; echo "df -i exit $?"
```

- `df -i` shows inode exhaustion, which looks like a full disk with space free. A directory full of small
  files, such as a cache or a logged run per item, is the usual cause.
- A full guest disk leaves truncated files. Procedure 3 of `SKILL.md` checks for zero-byte and
  unparseable files.

On WSL2 the guest's disk is a virtual disk file on a Windows drive. The Windows drive can fill while the
guest reports space free, because the virtual disk file grows and the guest cannot see the host drive.
Check the host drive from the guest, read-only, if Windows interop is enabled:

```sh
powershell.exe -NoProfile -Command "Get-PSDrive -PSProvider FileSystem | Format-Table Name,Used,Free -AutoSize"; echo "exit $?"
```

- If interop is disabled, the command fails. Say the host drive could not be checked, and ask the owner
  to check it from Windows. Do not guess that it was fine.
- A host drive at or near full explains a crash that left no guest-side error.

## WSL2 restarts and Windows-side reboots

A Windows restart stops the WSL2 virtual machine too. A WSL2 shutdown alone restarts only the guest.
The guest's `uptime` shows the difference: a short uptime with the Windows boot time much earlier means
only the guest restarted.

From the guest, read-only:

```sh
wsl.exe --status        ; echo "exit $?"               # WSL version and default distribution
wsl.exe --list --verbose ; echo "exit $?"              # distribution state: Running or Stopped
```

On the Windows side, the System event log records the reason for a restart. Run this read-only from the
guest if interop is enabled:

```sh
powershell.exe -NoProfile -Command "Get-WinEvent -FilterHashtable @{LogName='System';Id=1074,41} -MaxEvents 5 | Format-List TimeCreated,Id,Message"; echo "exit $?"
```

- Event 1074 records a restart or shutdown that was initiated, with the initiating process and reason.
  A Windows Update restart appears here with its reason.
- Event 41 from Kernel-Power records an unexpected restart with no clean shutdown: a crash or power loss.
- If interop is off, the Windows Update history and the event log are the owner's to read. Ask for the
  time and reason of the last restart.

## Recording what could not be established

Write the cause as one of:
- established, with the evidence line and its time;
- probable, with the evidence and what would confirm it;
- not established, with the reason (volatile journal, interop off, log missing).

Do not write "probably a Windows update" without the event that shows it. Do not write "no crash" when
the journal for that boot is missing.
