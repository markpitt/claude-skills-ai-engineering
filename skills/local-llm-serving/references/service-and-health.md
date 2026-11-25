# Service, linger and health checks

## Contents

- The systemd user unit
- Installing and enabling
- Linger: start at boot, not at login
- The silent-skip trap (ConditionPathExists)
- Health-check sequence
- Logs and status

## The systemd user unit

Run the proxy as a user service, not as root, and not from a terminal or tmux pane.

```ini
[Unit]
Description=Local llama-swap model proxy
Documentation=https://github.com/mostlygeek/llama-swap
ConditionFileIsExecutable=%h/.local/share/llama-swap/llama-swap
ConditionPathExists=%h/llama-swap/config.yaml

[Service]
Type=simple
WorkingDirectory=%h/llama-swap
ExecStart=%h/.local/share/llama-swap/llama-swap -config %h/llama-swap/config.yaml -listen 127.0.0.1:8080
Restart=on-failure
RestartSec=5s
TimeoutStopSec=30s
KillMode=control-group

[Install]
WantedBy=default.target
```

- `%h` is the user's home directory. Use it so the unit needs no absolute path.
- `-listen 127.0.0.1:8080` binds to loopback only. Do not bind to all interfaces unless a client on
  another machine needs it, and then put it behind an allowlist or a gateway.
- `KillMode=control-group` stops the proxy and every llama-server it started. Use it so no orphaned
  model keeps the GPU busy after a stop.
- `Restart=on-failure` restarts after a crash. A deliberate `systemctl --user stop` stays stopped.
- `TimeoutStopSec` must allow a model to unload. Ten to thirty seconds is typical.

If llama-server must find the WSL GPU libraries, add an `Environment=` line (see `wsl2-gpu.md`).

## Installing and enabling

```sh
mkdir -p ~/.config/systemd/user
# write the unit to ~/.config/systemd/user/llama-swap.service, then:
systemctl --user daemon-reload
systemctl --user enable --now llama-swap.service
systemctl --user is-enabled llama-swap.service     # prints "enabled"
systemctl --user is-active llama-swap.service      # prints "active"
```

## Linger: start at boot, not at login

A user unit runs only while the user's systemd instance runs. Without linger, that instance starts at the
first login and stops at the last logout, so the proxy is down after a reboot until someone logs in.

```sh
loginctl show-user "$USER" -p Linger              # Linger=yes means it is on
sudo loginctl enable-linger "$USER"               # turn it on if it reports no
```

On WSL2, the distribution itself starts when something asks for it. Systemd runs inside it only when
`/etc/wsl.conf` enables it (`[boot]` then `systemd=true`). Without that, there is no user manager to
run the unit at all. See `wsl2-gpu.md`.

## The silent-skip trap

`ConditionPathExists` and `ConditionFileIsExecutable` make systemd skip the unit, with exit status 0,
when the config or the binary is missing. `systemctl start` then appears to succeed and nothing runs.

```sh
systemctl --user status llama-swap.service --no-pager
# look for: "Condition check resulted in ... being skipped" or "condition failed"
```

If the status shows a skipped condition, fix the path, do not remove the condition to get past it. A
missing config should stop the service, not start it without one.

## Health-check sequence

Run in this order. Each step narrows the fault. Stop at the first failure and read its message.

1. **The unit is running.**

   ```sh
   systemctl --user is-active llama-swap.service; echo "exit $?"
   ```

2. **The proxy answers and lists the configured ids.** This does not load any model.

   ```sh
   curl -fsS --max-time 10 "$LLAMA_URL/v1/models"; echo "exit $?"
   ```

   A 404 on a path the build does not have means the proxy or the build is older than the client expects.

3. **The GPU is visible and the card's memory is as expected.**

   ```sh
   nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv
   ```

   On WSL2 the binary may be at `/usr/lib/wsl/lib/nvidia-smi`. If it is not found there either, see
   `wsl2-gpu.md`.

4. **A model loads and answers.** The first request after a swap is the cold load, so give it time.

   ```sh
   curl -fsS --max-time 300 -w '\ntime_total=%{time_total}\n' "$LLAMA_URL/v1/chat/completions" \
     -H 'Content-Type: application/json' \
     -d '{"model":"<model-id>","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":4,"stream":false}'
   echo "exit $?"
   ```

5. **A second request is fast.** Run step 4 again. It should return in a second or two for a small model.
   If it is slow, the model is running on the CPU or the context is being re-processed; see
   `load-failures.md`.

6. **The model is on the GPU.** Memory should have risen by roughly the footprint measured in
   `vram-and-disk-planning.md`, and the proxy log should report full offload.

Keep the probe small: `max_tokens` of a few tokens, and one request. The probe proves the path, not quality.

## Logs and status

```sh
systemctl --user status llama-swap.service --no-pager
journalctl --user -u llama-swap -b --no-pager | tail -n 100   # this boot, last 100 lines
journalctl --user -u llama-swap --since "-1 h" --no-pager      # the last hour
```

`-b` means the current boot. After a reboot, the previous boot's log is `-b -1` (see `resume-after-crash`
if the log is missing). Piping to `tail` is fine for reading; when you are searching for failures, keep
the search's exit code (see `SKILL.md`, procedure 8).
