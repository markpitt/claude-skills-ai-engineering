# NET=proxy: the allowlisting proxy, and what a sandboxed Claude client needs

Read this when an agent must reach Anthropic from inside the sandbox (`NET=proxy`). Everything here was
found the slow way, installing an agent for `~/.claude` on a WSL host on 15/10/2026.

## Shape

The sandbox has no network. `sandbox.sh` binds a unix socket into it and runs `socat` there, so the
client sees `HTTPS_PROXY=http://127.0.0.1:3128`; on the host a second `socat` forwards that socket to
`PROXY_ADDR` (default `127.0.0.1:8888`). Something must be listening there, and it is the only thing
that decides what the agent can reach.

`scripts/install-proxy.sh` installs one: `scripts/allowlist-proxy.py`, a CONNECT-only proxy that tunnels
port 443 to hosts named in `~/sandboxes/proxy/allowlist.txt` and refuses everything else (403, plain
HTTP 405). It logs host and verdict only, and re-reads the allowlist on every request, so adding a host
needs no restart. It resolves a host before connecting and refuses one that points at a loopback, LAN or
link-local address (an allowlisted name hijacked by local DNS cannot reach the LAN). A lookup is reused for
`PROXY_DNS_TTL` seconds (60; 0 resolves every tunnel), since Claude Code opens a new connection every few
seconds; the address check still runs on every tunnel, and a failed dial drops the cached answer. It gives a client 15
seconds to send its CONNECT line, caps concurrent connections (`PROXY_MAX_CONNECTIONS`, 64) so one agent
cannot hold every thread of a proxy all agents share, and runs under a hardened systemd unit.

```
bash scripts/install-proxy.sh               # systemd user unit sandbox-allowlist-proxy.service
journalctl --user -u sandbox-allowlist-proxy -o cat | sort | uniq -c | sort -rn     # who asked for what
```

## Allow-all instance, blocked by exception

An agent that is meant to roam the public internet (research, docs, downloads) can get its own proxy instance whose allowlist
starts with a `*` line. `*` allows every host that resolves to a public address; the LAN, loopback and link-local refusal still applies
to every tunnel. Block by adding a line, no restart: `!host` blocks one host, `!*.domain` blocks the domain and everything under it.
A block beats an allow, also an exact one. Every host is logged with its verdict, so the log shows what to block.

```
printf '*\n!*.example-ads.com\n' > ~/sandboxes/proxy/allowlist-roam.txt     # then PROXY_INSTANCE=roam PROXY_PORT=8893 bash scripts/install-proxy.sh
```

## One local endpoint, read-only

An agent that must read one endpoint of a service on the host (a model list, a status page) gets a line in an
allowlist of the form `GET http://127.0.0.1:8080/v1/models`: method, scheme, host, port and path, verbatim.
The proxy forwards that one request, rebuilt by itself with its own headers and no body, and relays the
reply. A different path, a query string, another method or port, another host name, or a CONNECT to the same
address is refused, and nothing the client sent beyond the request line reaches the service. Plain HTTP
for anything not listed is still refused with 405.

What it does not do: it is not a filter on the service. Whatever the listed URL does when fetched happens,
and the answer comes back whole. The allowance lives in the allowlist it is written in, and the default
allowlist is shared by every agent. To give one agent the line, run a second proxy:

```
PROXY_INSTANCE=llama PROXY_PORT=8889 bash scripts/install-proxy.sh   # allowlist-llama.txt, sandbox-allowlist-proxy-llama.service
```

and set `PROXY_ADDR=127.0.0.1:8889` in that agent's profile. Inside the sandbox the loopback is the sandbox's own,
so the agent names the host-side address through the proxy: `curl -x http://127.0.0.1:3128 http://127.0.0.1:8080/v1/models`
(the bridge port printed by `<name>-sandbox show`).

Re-running `install-proxy.sh` replaces the script and restarts the unit, so an upgrade takes effect at once; every
agent's open tunnels on that proxy drop and reconnect.

## Hosts: start with two

| Host | Why | Verdict |
|---|---|---|
| `api.anthropic.com` | the model API | allow |
| `platform.claude.com` | OAuth token exchange for `/login`; without it login fails with `ERR_PROXY_TUNNEL` | allow |
| `downloads.claude.ai` | auto-update downloads | deny; set `DISABLE_AUTOUPDATER` instead |
| `http-intake.logs.us5.datadoghq.com` | client telemetry | deny; set `DISABLE_ERROR_REPORTING`. `DISABLE_TELEMETRY` is not set, because an agent with it cannot be reached over Remote Control |
| `mcp-proxy.anthropic.com` and the ~45 `mcp.*` hosts | the logged-in account's claude.ai connectors | deny; set `ENABLE_CLAUDEAI_MCP_SERVERS=false` |
| ~55 vendor hosts (`mcp.slack.com`, `mcp.asana.com`, `mcp.stripe.com`, `api.githubcopilot.com` and others), at each session start | MCP servers declared by plugins claude.ai syncs to the account (`plugins/synced/*/.mcp.json` in the agent's config directory); the connectors switch does not cover them | deny; set `CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS=1` (measured 17/11/2026 on 2.1.325: 0 of these after the restart) |
| `raw.githubusercontent.com` | an optional fetch (changelog or marketplace) | deny unless something needs it |

Add a host only from an observed denial in the log, one at a time, and write the reason beside it.

## Fix the client, not the proxy

A refused connection shows as an error in the UI whether the proxy denies it, drops it or hangs, so
"drop instead of deny" changes nothing for the user (and a fake 200 makes the allowlist lie). The agent
is logged in as the user, so by default it tries every connector the account has: dozens of refused
connections, and each one is a way out of the sandbox if allowed. Switch the traffic off at the source.
`scripts/client-env.sh` (run by `new-agent.sh`) merges this into the agent's `settings.json`:

```json
"env": {
  "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
  "CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS": "1",
  "DISABLE_ERROR_REPORTING": "1",
  "DISABLE_AUTOUPDATER": "1"
}
```

### Cross-session messaging

The same script closes the messaging door, which is not network traffic and so cannot be closed at the
proxy: Remote Control and peer messages travel through `api.anthropic.com`, which the agent needs.

| Setting | Controls |
|---|---|
| `crossSessionInbound`: `accept`, `hold`, `refuse` | what arrives. `refuse` drops each message; set to `refuse`. |
| `permissions.deny`: `SendMessage`, `ListAgents` | what the agent can send and list. Both take the bare tool name. |
| `isolatePeerMachines` | approval before a message leaves the machine; not an off switch |

Source: <https://code.claude.com/docs/en/cross-session-messaging>, "Turn off cross-session messaging".
Measured 15/10/2026 on 2.1.294: with `refuse` set and the session restarted, the sender's `SendMessage`
was refused before it left ("can't receive cross-session messages (off in that session)"). Before the
setting, a harmless peer message reached the agent and a Haiku agent with an instruction file declined
it. The docs say a refusing session shows no change in `/status`; to confirm from the sender, send one
and read the refusal. Not tested: the receiver dropping a message from a local peer, and that the user's
own typing over Remote Control is unaffected (the setting is defined for messages "from your other
sessions"). An agent that must take messages sets `ALLOW_MESSAGING=1` in its profile (persistent and
reversible) or `SANDBOX_ALLOW_MESSAGING=1` for one install; see `SKILL.md` for `hold`.

A value the user already set wins. For `NET=host`, where the network is shared anyway, `new-agent.sh`
leaves the connectors and plugin MCP servers on (`client-env.sh <dir> keep-connectors`). Restart the agent session after
changing settings.

## Other things this install hit

- **Ask rules are `Edit(...)` only.** Claude Code ignores `Write(...)` rules and reports each as an error;
  `protect-config.sh` writes Edit rules and removes the Write ones an older run added.
- **Binds must exist.** Some distros have no `/etc/nsswitch.conf` or `/etc/ca-certificates`, and
  `/etc/ssl/certs` may point into `/var/lib/ca-certificates`; `sandbox.sh` binds only what is there.
- **Interactive login.** Run `<name>-sandbox shell`, then `claude` and `/login`. The login lands in the
  agent's config directory, not the host's. A scoped token in the env file (`PASS_ENV`) is the alternative.
- **Testing inside a read-only sandbox.** When the tests run in a wrapper that leaves `$HOME` read-only, so give every test profile an
  `AGENT_HOME` and `XDG_RUNTIME_DIR` inside its temp dir (`scripts/test.sh` does).
- **`NET=proxy` is only as strict as the allowlist**, and the proxy is a host-wide service shared by every
  agent on the machine: an allowance for one agent is an allowance for all.
