#!/usr/bin/env bash
# Install the host-side allowlisting proxy that NET=proxy sandboxes tunnel through, as a systemd user
# service. Idempotent; never overwrites an allowlist the user has edited.
#   install-proxy.sh [dir]        default dir: $SANDBOX_BASE/proxy (~/sandboxes/proxy)
#   PROXY_INSTANCE=<name> PROXY_PORT=<port> install-proxy.sh   a second proxy with its own allowlist
#       (allowlist-<name>.txt, unit sandbox-allowlist-proxy-<name>.service), so an allowance can be for
#       one agent: point that agent's PROXY_ADDR at the port.
# The allowlist is re-read on every request, so adding a host needs no restart. See references/proxy.md.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DIR=${1:-${SANDBOX_BASE:-$HOME/sandboxes}/proxy}
UNIT_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
PY=$(command -v python3) || { echo "install-proxy: python3 not found" >&2; exit 1; }
INST=${PROXY_INSTANCE:-}; PORT=${PROXY_PORT:-8888}
case "$INST" in *[!A-Za-z0-9_-]*) echo "install-proxy: PROXY_INSTANCE may hold letters, digits, - and _" >&2; exit 1;; esac
case "$PORT" in ''|*[!0-9]*) echo "install-proxy: PROXY_PORT must be a number" >&2; exit 1;; esac
[ -z "$INST" ] || [ "$PORT" != 8888 ] || { echo "install-proxy: an instance needs its own PROXY_PORT" >&2; exit 1; }
SUF=${INST:+-$INST}; LIST=$DIR/allowlist$SUF.txt; UNIT=sandbox-allowlist-proxy$SUF.service
for u in "$UNIT_DIR"/sandbox-allowlist-proxy*.service; do
  [ -e "$u" ] && [ "$(basename "$u")" != "$UNIT" ] || continue
  if grep -qx "Environment=PROXY_PORT=$PORT" "$u" || { [ "$PORT" = 8888 ] && ! grep -q '^Environment=PROXY_PORT=' "$u"; }; then
    echo "install-proxy: port $PORT is already used by $(basename "$u")" >&2; exit 1
  fi
done
mkdir -p "$DIR" "$UNIT_DIR"
install -m 755 "$HERE/allowlist-proxy.py" "$DIR/allowlist-proxy.py"
if [ ! -e "$LIST" ]; then
  printf '%s\n' '# Hosts the sandboxed agents may CONNECT to on 443. One per line.' \
    'api.anthropic.com' \
    'platform.claude.com   # OAuth token exchange for /login' > "$LIST"
fi
cat > "$UNIT_DIR/$UNIT" <<UNIT
[Unit]
Description=Allowlisting CONNECT proxy for NET=proxy sandboxed agents (127.0.0.1:$PORT)

[Service]
Environment=PROXY_PORT=$PORT
Environment=PROXY_ALLOWLIST=$LIST
ExecStart=$PY -I $DIR/allowlist-proxy.py
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=read-only
ProtectSystem=strict

[Install]
WantedBy=default.target
UNIT
if systemctl --user daemon-reload 2>/dev/null; then
  systemctl --user enable "$UNIT"
  systemctl --user restart "$UNIT"      # start is a no-op on a running unit, which would keep the old code
  sleep 1; systemctl --user is-active "$UNIT"
else
  echo "no systemd user manager: run  $PY -I $DIR/allowlist-proxy.py  under your own supervisor" >&2
fi
echo "allowlist: $LIST   log: journalctl --user -u ${UNIT%.service} -o cat"
