# Running under WSL2

The NVIDIA driver runs on the Windows host. WSL2 exposes the GPU to the Linux guest through a stub
library set, so Linux tools can use the card without a Linux driver of their own. Most WSL2 GPU
failures are someone installing a Linux driver into the guest, or a service that starts before the
guest is ready.

## Contents

- Check the GPU is passed through
- Never install a Linux display driver in the guest
- Library path for the service
- Systemd, boot and linger
- Disk: where models live, and the virtual disk
- Memory: the WSL2 cap
- Restarting WSL2 interrupts everything

## Check the GPU is passed through

```sh
grep -qi microsoft /proc/version && echo "running under WSL"
ls -l /usr/lib/wsl/lib/nvidia-smi                 # the guest's copy of the NVIDIA tool
/usr/lib/wsl/lib/nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
```

- The `nvidia-smi` in `/usr/lib/wsl/lib` is the one that works. It may not be on `PATH` in a service's
  environment, so use the full path in units and scripts.
- If the file is missing, the GPU is not passed through. Check the Windows side first: the NVIDIA driver
  must be installed on Windows and be a WSL-capable version. Then run `wsl --update` from Windows, and
  `wsl --shutdown` only after confirming no other agent is using the GPU (see the last section).
- If the tool runs but reports no devices, the Windows driver or the WSL kernel is out of date.

## Never install a Linux display driver in the guest

- Do not install `nvidia-driver-*` or any package that brings a Linux kernel driver into WSL2. It
  replaces or shadows the passed-through libraries and breaks the GPU for the whole guest.
- A CUDA toolkit is fine if it is installed without its driver component. Use the toolkit package, not
  a meta-package that also pulls the driver. The NVIDIA WSL guide lists the correct package for each
  distribution.
- If `nvidia-smi` breaks after an install, remove the package that brought the driver. Do not reinstall
  the Windows driver to fix a Linux package.

## Library path for the service

llama-server links against the CUDA libraries. In a systemd user unit, the WSL library directory is not
on the default search path unless the unit adds it:

```ini
[Service]
Environment=LD_LIBRARY_PATH=/usr/lib/wsl/lib
```

Add it only if `llama-server` reports it cannot load a CUDA library. Check with `ldd` on the binary
before adding it, and keep the change in the unit file, not in the shell profile, so it applies to
services and interactive shells alike.

## Systemd, boot and linger

- Enable systemd in the distribution. In `/etc/wsl.conf`:

  ```ini
  [boot]
  systemd=true
  ```

  Then run `wsl --shutdown` from Windows and start the distribution again. This step needs the
  distribution to be idle: follow the rule below first.
- Without systemd, there is no user manager, so the llama-swap unit cannot start at boot.
- The distribution starts when something runs in it. Linger keeps the user manager alive after logins
  end, so the proxy stays up while the distribution runs (see `service-and-health.md`). It does not
  start the distribution on Windows boot by itself: a scheduled task on the Windows side, or a
  deliberate start, does that.

## Disk: where models live, and the virtual disk

- Keep GGUF files on the Linux filesystem. Files under a Windows drive mount (`/mnt/c` and similar) cross
  a slower protocol layer, and a cold load can take several times longer, which trips
  `healthCheckTimeout`.
- The distribution's ext4 disk is a virtual disk file on the Windows drive. It grows when files are
  added. Deleting a model frees space inside the guest only. The Windows drive does not regain the space
  until the virtual disk is compacted.
- To compact, shut the distribution down (after the rule below), then compact the virtual disk from an
  elevated Windows PowerShell with the Hyper-V tools, or use the newer `wsl --manage` sparse setting
  where the WSL release supports it. Check the release notes for the WSL version installed.
- Watch the Windows drive's free space as well as the guest's `df -h`. A full Windows drive stops the
  distribution writing anything, including logs.

## Memory: the WSL2 cap

- Host RAM for the guest is capped by a Windows-side setting. A model's host-side buffers count against
  that cap as well as the GPU budget.
- Changing the cap needs `wsl --shutdown`, which stops every process in the distribution, including the
  proxy and any model loaded in it.

## Restarting WSL2 interrupts everything

`wsl --shutdown`, a Windows update reboot, or a crash of the distribution stops llama-swap and every
loaded model. Clients get connection errors until the distribution and the unit are back. Before
shutting WSL2 down:

1. Check the GPU and connections (procedure 6 in `SKILL.md`).
2. Confirm with the owner of any session that depends on the proxy. Do not shut the distribution down
   under another agent's work.
3. After the restart, run the health-check sequence from the start, not just the unit status.
