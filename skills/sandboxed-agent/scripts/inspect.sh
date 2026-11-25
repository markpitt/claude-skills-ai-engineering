#!/usr/bin/env bash
# Look at a folder and print what a sandbox for an agent working there should hide, plus the
# questions that cannot be answered from the contents. Read-only: it writes nothing.
#   inspect.sh <folder>
set -uo pipefail
D=${1:-}; [ -d "$D" ] || { echo "usage: inspect.sh <folder>" >&2; exit 2; }
D=$(cd "$D" && pwd -P)
shopt -s nullglob dotglob

echo "ROOT=$D"
kind=unknown
[ -n "$(find "$D" -maxdepth 4 \( -name 'docker-compose*.y*ml' -o -name 'compose.y*ml' \) 2>/dev/null | head -1)" ] && kind=compose
[ -f "$D/configuration.yaml" ] && [ -d "$D/custom_components" -o -d "$D/.storage" ] && kind=home-assistant
[ "$kind" = unknown ] && [ -f "$D/package.json" ] && kind=node
for f in package.json pyproject.toml go.mod Cargo.toml; do [ "$kind" = unknown ] && [ -f "$D/$f" ] && kind=code; done
echo "KIND=$kind"
[ -e "$D/.git" ] && echo "GIT=yes (history is writable if ROOT_MODE=rw; the sandbox has no push credentials)" || echo "GIT=no"
echo "OWNER_MIX=$(find "$D" -maxdepth 2 -printf '%u\n' 2>/dev/null | sort -u | paste -sd,)"

echo "--- BLANK candidates (relative; secrets and state)"
{
  find "$D" -maxdepth 4 \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' -o -name 'id_rsa*' -o -name 'id_ed25519*' \
       -o -name 'secrets*.y*ml' -o -name 'secrets*.json' -o -name '*.kdbx' -o -name 'acme.json' -o -name '*credentials*' \
       -o -name '*.token' -o -name '.netrc' -o -name '*.p12' -o -name '*.pfx' \) -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null
  for n in .storage .cloud backups certs certificates ssh .ssh secrets .secrets private; do find "$D" -maxdepth 3 -type d -name "$n" -not -path '*/.git/*' 2>/dev/null; done
  find "$D" -maxdepth 3 \( -name '*.db' -o -name '*.db-wal' -o -name '*.sqlite*' -o -name '*.rdb' \) 2>/dev/null
} | sed "s#^$D/##" | sort -u | sed 's/^/BLANK: /'

echo "--- large files (>50 MB; usually state, not config)"
find "$D" -maxdepth 4 -type f -size +50M -not -path '*/.git/*' 2>/dev/null | sed "s#^$D/#LARGE: #"

echo "--- logs and app data (readable but noisy or private; decide)"
for n in logs log data files tts cache .cache deps tmp; do [ -d "$D/$n" ] && echo "MAYBE: $n ($(du -sh "$D/$n" 2>/dev/null | cut -f1))"; done

echo "--- questions the folder cannot answer"
echo "ASK: should the agent edit files in place (rw) or only read them and act through an API (ro)?"
echo "ASK: does the agent need the network? none (default), proxy to an allowlist, or the host's"
[ "$kind" = compose ] && echo "ASK: does it need the Docker API? (a read-only socket proxy is the safe way)"
[ "$kind" = home-assistant ] && echo "ASK: should it reach the Home Assistant API for config checks? (needs a URL and a token)"
echo "ASK: which tool or service does this folder belong to, so related host notes can be found?"
