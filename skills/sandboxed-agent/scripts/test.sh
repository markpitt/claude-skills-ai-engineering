#!/usr/bin/env bash
# Build a throwaway folder and prove sandbox.sh and inspect.sh for each network mode and root mode.
#   bash scripts/test.sh        (needs bwrap, socat, curl)
set -u
H=$(cd "$(dirname "$0")" && pwd)
D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
export XDG_RUNTIME_DIR=$D   # the proxy bridge socket goes here, not into the real runtime dir
mkdir -p "$D/proj/data" "$D/proj/logs"
echo "KEY=abc" > "$D/proj/.env"; echo hi > "$D/proj/app.yml"; echo s > "$D/proj/data/x"; echo k > "$D/proj/id.pem"
fail=0
for mode in "none ro" "none rw" "proxy ro" "host ro"; do
  set -- $mode
  # AGENT_HOME inside $D: the default is ~/.<name>-agent, which litters the real home and fails where it is read-only
  printf 'NAME=t%s%s\nROOT=%s\nROOT_MODE=%s\nNET=%s\nAGENT_HOME=%s\nBLANK=( ".env" "data" "*.pem" )\n' "$1" "$2" "$D/proj" "$2" "$1" "$D/agent-$1-$2" > "$D/p"
  echo "== NET=$1 ROOT_MODE=$2"
  bash "$H/sandbox.sh" "$D/p" test | tail -1 | tee /dev/stderr | grep -q " 0 failed" || fail=1
done
echo "== seccomp: what the namespaces do not cover"
# AF_VSOCK is not network-namespaced, so NET=none alone still reaches a VM host (Crostini, WSL2).
printf 'NAME=tsec\nROOT=%s\nROOT_MODE=ro\nNET=none\nAGENT_HOME=%s\n' "$D/proj" "$D/agent-sec" > "$D/psec"
# Filters are inherited (a container such as Crostini's LXC already has one), so "Seccomp: 2" proves
# nothing: count the filters instead. sandbox.sh must add one to what test.sh itself runs under.
outer=$(sed -n 's/^Seccomp_filters:[[:space:]]*//p' /proc/self/status); outer=${outer:-0}   # sed, not awk: Debian's awk is an /etc/alternatives link
if [ ! -x /usr/bin/python3 ]; then echo "FAIL  the seccomp cases need /usr/bin/python3 inside the sandbox"; fail=1
else
  sec=$(bash "$H/sandbox.sh" "$D/psec" run -- python3 -I -c '
import socket, ctypes, errno
def sock(fam):
    try: socket.socket(fam, socket.SOCK_STREAM).close(); return "ok"
    except OSError as e: return errno.errorcode.get(e.errno, str(e.errno))
libc = ctypes.CDLL(None, use_errno=True)
uring = "ok" if libc.syscall(425, 8, ctypes.create_string_buffer(120)) >= 0 else errno.errorcode.get(ctypes.get_errno())
st = open("/proc/self/status").read(); nfil = st.split("Seccomp_filters:")[1].split()[0] if "Seccomp_filters:" in st else "unknown"
print(sock(socket.AF_VSOCK), sock(socket.AF_INET), sock(socket.AF_UNIX), uring, nfil)' 2>&1)
  set -- $sec
  [ "${5:-x}" -gt "$outer" ] 2>/dev/null && echo "ok    sandbox.sh adds a seccomp filter ($outer outside, ${5} inside)" || { echo "FAIL  no added seccomp filter ($outer outside): $sec"; fail=1; }
  [ "${1:-}" = EAFNOSUPPORT ] && echo "ok    an AF_VSOCK socket is refused" || { echo "FAIL  AF_VSOCK: $sec"; fail=1; }
  [ "${2:-}${3:-}" = okok ] && echo "ok    AF_INET and AF_UNIX sockets still work" || { echo "FAIL  ordinary sockets: $sec"; fail=1; }
  [ "${4:-}" = ENOSYS ] && echo "ok    io_uring is refused (it can open sockets without socket())" || { echo "FAIL  io_uring: $sec"; fail=1; }
fi
echo "== EXTRA_RW: a writable bind the agent cannot replace"
mkdir -p "$D/spool"
printf 'NAME=trw\nROOT=%s\nROOT_MODE=ro\nNET=none\nAGENT_HOME=%s\nEXTRA_RW=( "%s:/run/spool" )\n' "$D/proj" "$D/agent-rw" "$D/spool" > "$D/prw"
bash "$H/sandbox.sh" "$D/prw" run -- sh -c 'echo hello > /run/spool/a.json' >/dev/null 2>&1
[ "$(cat "$D/spool/a.json" 2>/dev/null)" = hello ] && echo "ok    a file written inside the sandbox appears on the host" || { echo "FAIL  EXTRA_RW write not seen on the host"; fail=1; }
rw_out=$(bash "$H/sandbox.sh" "$D/prw" run -- sh -c 'rmdir /run/spool 2>&1; mv /run/spool /run/spool2 2>&1; ls /run/spool' 2>&1)
[ -d "$D/spool" ] && grep -q "a.json" <<<"$rw_out" && echo "ok    the mount point cannot be removed or renamed from inside" || { echo "FAIL  EXTRA_RW mount point replaced: $rw_out"; fail=1; }
miss=$(sed "s#$D/spool#$D/not-there#" "$D/prw" > "$D/prw2"; bash "$H/sandbox.sh" "$D/prw2" run -- true 2>&1); grep -q "bind source '$D/not-there' does not exist" <<<"$miss" && echo "ok    a missing bind source is named, not a bwrap error" || { echo "FAIL  missing bind source message: $miss"; fail=1; }
bash "$H/sandbox.sh" "$D/p" run -- sh -c 'test -e /run/spool' >/dev/null 2>&1 && { echo "FAIL  EXTRA_RW leaked into a profile without it"; fail=1; } || echo "ok    a profile without EXTRA_RW has no such mount"
echo "== ROOT below a protected home path"
# the real-home check must not fire when ROOT is mounted on purpose under ~/.config (or .ssh, .claude)
FH=$D/fakehome; mkdir -p "$FH/.config/zz-root"; echo hi > "$FH/.config/zz-root/app.yml"
printf 'NAME=tunder\nROOT=%s\nROOT_MODE=ro\nNET=none\nAGENT_HOME=%s\nBLANK=( )\n' "$FH/.config/zz-root" "$D/agent-under" > "$D/pu"
HOME=$FH bash "$H/sandbox.sh" "$D/pu" test | tail -1 | tee /dev/stderr | grep -q " 0 failed" || fail=1
echo "== ROOT is the home folder itself"
# an agent across every repository in the home folder mounts the real home on purpose: the real-home check is skipped with a note, the
# blank list is the test, and the run still reports 0 failed
FH2=$D/fakehome2; mkdir -p "$FH2/.ssh" "$FH2/.claude" "$FH2/.config"; echo k > "$FH2/.ssh/id_x"
printf 'NAME=tme\nROOT=%s\nROOT_MODE=ro\nNET=none\nAGENT_HOME=%s\nBLANK=( .ssh )\nEXTRA_RW=( "%s:%s" )\n' "$FH2" "$D/agent-me" "$D/agent-me" "$FH2/.tme-agent" > "$D/pme"
mkdir -p "$D/agent-me" "$FH2/.tme-agent"
me_out=$(HOME=$FH2 bash "$H/sandbox.sh" "$D/pme" test 2>&1)
grep -q "^note  ROOT is the home folder" <<<"$me_out" && ! grep -q "real home" <<<"$(grep -v '^note' <<<"$me_out")" && grep -q "ok    blank dir  .ssh" <<<"$me_out" \
  && echo "ok    ROOT=\$HOME: the real-home check is replaced by a note and the blank list" || { echo "FAIL  ROOT=\$HOME self-test: $(tail -3 <<<"$me_out")"; fail=1; }
grep -q " 0 failed" <<<"$me_out" && echo "ok    ROOT=\$HOME: 0 failed" || { echo "FAIL  ROOT=\$HOME: $(tail -1 <<<"$me_out")"; fail=1; }
echo "== exit status"
# an EXIT trap's last status becomes the script's: show and a passing test must exit 0, a failing command must still exit non-zero
bash "$H/sandbox.sh" "$D/p" show >/dev/null 2>&1 && echo "ok    show exits 0" || { echo "FAIL  show exits non-zero"; fail=1; }
bash "$H/sandbox.sh" "$D/p" test >/dev/null 2>&1 && echo "ok    a passing test exits 0" || { echo "FAIL  a passing test exits non-zero"; fail=1; }
bash "$H/sandbox.sh" "$D/p" run -- false >/dev/null 2>&1 && { echo "FAIL  run of a failing command exits 0"; fail=1; } || echo "ok    run of a failing command exits non-zero"
echo "== client-env.sh"
mkdir -p "$D/cenv"; echo '{"theme":"dark","env":{"DISABLE_TELEMETRY":"0"}}' > "$D/cenv/settings.json"
bash "$H/client-env.sh" "$D/cenv" >/dev/null; bash "$H/client-env.sh" "$D/cenv" >/dev/null
ce="$D/cenv/settings.json"
[ "$(jq -r '.env.ENABLE_CLAUDEAI_MCP_SERVERS' "$ce")" = false ] && echo "ok    account connectors switched off" || { echo "FAIL  connectors env"; fail=1; }
# plugins claude.ai syncs to the account declare their own MCP servers, which the connectors switch does not cover
[ "$(jq -r '.env.CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS' "$ce")" = 1 ] && echo "ok    plugin MCP servers switched off" || { echo "FAIL  plugin MCP env: $(jq -c .env "$ce")"; fail=1; }
mkdir -p "$D/cenvk"; bash "$H/client-env.sh" "$D/cenvk" keep-connectors >/dev/null
[ "$(jq -r '.env.DISABLE_AUTOUPDATER,(.env|has("ENABLE_CLAUDEAI_MCP_SERVERS")),(.env|has("CLAUDE_CODE_SKIP_PLUGIN_MCP_SERVERS"))' "$D/cenvk/settings.json" | paste -sd,)" = "1,false,false" ] \
  && echo "ok    keep-connectors leaves connectors and plugin MCP servers on" || { echo "FAIL  keep-connectors env: $(jq -c .env "$D/cenvk/settings.json")"; fail=1; }
[ "$(jq -r '.env.DISABLE_TELEMETRY,.theme' "$ce" | paste -sd,)" = "0,dark" ] && echo "ok    user's own env value and settings kept" || { echo "FAIL  client-env merge"; fail=1; }
# cross-session messaging: an agent on Remote Control is a message target for every session on the account
[ "$(jq -r '.crossSessionInbound' "$ce")" = refuse ] && echo "ok    inbound peer messages are refused" || { echo "FAIL  crossSessionInbound: $(jq -c .crossSessionInbound "$ce")"; fail=1; }
[ "$(jq -c '.permissions.deny|sort' "$ce")" = '["ListAgents","SendMessage"]' ] && echo "ok    SendMessage and ListAgents are denied" || { echo "FAIL  deny rules: $(jq -c .permissions.deny "$ce")"; fail=1; }
mkdir -p "$D/cenv3"; echo '{"crossSessionInbound":"hold","permissions":{"deny":["Bash(rm:*)"]}}' > "$D/cenv3/settings.json"
bash "$H/client-env.sh" "$D/cenv3" >/dev/null
[ "$(jq -r '.crossSessionInbound' "$D/cenv3/settings.json")" = hold ] && echo "ok    a crossSessionInbound the user set is kept" || { echo "FAIL  user inbound value overwritten"; fail=1; }
[ "$(jq -c '.permissions.deny|sort' "$D/cenv3/settings.json")" = '["Bash(rm:*)","ListAgents","SendMessage"]' ] && echo "ok    the user's own deny rule is kept" || { echo "FAIL  deny merge"; fail=1; }
mkdir -p "$D/cenv4"; bash "$H/client-env.sh" "$D/cenv4" allow-messaging >/dev/null
[ "$(jq -r 'has("crossSessionInbound")' "$D/cenv4/settings.json")" = false ] && [ "$(jq -r '.permissions.deny // [] | length' "$D/cenv4/settings.json")" = 0 ] \
  && echo "ok    allow-messaging leaves a fresh file alone" || { echo "FAIL  allow-messaging on a fresh file"; fail=1; }
# Remote Control needs telemetry on: a fresh file gets no DISABLE_TELEMETRY, the other client settings still apply
[ "$(jq -c '[(.env | has("DISABLE_TELEMETRY")), .env.DISABLE_ERROR_REPORTING]' "$D/cenv4/settings.json")" = '[false,"1"]' ] \
  && echo "ok    telemetry is left on, error reporting is off" || { echo "FAIL  telemetry env: $(jq -c .env "$D/cenv4/settings.json")"; fail=1; }
# allow-messaging must be reversible: remove exactly what this script adds, keep the user's own rules
mkdir -p "$D/cenv5"; echo '{"permissions":{"deny":["Bash(rm:*)","SendMessage","ListAgents"]},"crossSessionInbound":"refuse"}' > "$D/cenv5/settings.json"
bash "$H/client-env.sh" "$D/cenv5" allow-messaging >/dev/null
[ "$(jq -r 'has("crossSessionInbound")' "$D/cenv5/settings.json")" = false ] && [ "$(jq -c '.permissions.deny' "$D/cenv5/settings.json")" = '["Bash(rm:*)"]' ] \
  && echo "ok    allow-messaging removes the block it added and keeps the user's own deny" || { echo "FAIL  allow-messaging did not reverse: $(jq -c '[.crossSessionInbound,.permissions.deny]' "$D/cenv5/settings.json")"; fail=1; }
mkdir -p "$D/cenv6"; echo '{"crossSessionInbound":"hold"}' > "$D/cenv6/settings.json"
bash "$H/client-env.sh" "$D/cenv6" allow-messaging >/dev/null
[ "$(jq -r '.crossSessionInbound' "$D/cenv6/settings.json")" = hold ] && echo "ok    allow-messaging keeps a hold the user chose" || { echo "FAIL  allow-messaging dropped hold"; fail=1; }
# the user's own deny list keeps its order (no sort)
mkdir -p "$D/cenv7"; echo '{"permissions":{"deny":["Zed","Alpha"]}}' > "$D/cenv7/settings.json"
bash "$H/client-env.sh" "$D/cenv7" >/dev/null
[ "$(jq -c '.permissions.deny' "$D/cenv7/settings.json")" = '["Zed","Alpha","SendMessage","ListAgents"]' ] && echo "ok    the user's deny list keeps its order" || { echo "FAIL  deny order: $(jq -c .permissions.deny "$D/cenv7/settings.json")"; fail=1; }
echo "== allowlist-proxy.py"
printf '# a comment, then a blank line\n\nallowed.invalid\n' > "$D/allow.txt"
PROXY_PORT=0 PROXY_ALLOWLIST=$D/allow.txt python3 -I "$H/allowlist-proxy.py" 2> "$D/proxy.log" & PX=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do grep -q listening "$D/proxy.log" && break; sleep 0.2; done
PP=$(sed -n 's/^listening 127.0.0.1:\([0-9]*\) .*/\1/p' "$D/proxy.log")
[ -n "$PP" ] || { echo "FAIL  proxy did not start: $(cat "$D/proxy.log")"; fail=1; PP=1; }
curl -s -o /dev/null --max-time 5 -x "http://127.0.0.1:$PP" "https://denied.invalid/" 2>/dev/null
curl -s -o /dev/null --max-time 5 -x "http://127.0.0.1:$PP" "https://allowed.invalid/" 2>/dev/null
curl -s -o /dev/null --max-time 5 -x "http://127.0.0.1:$PP" "http://allowed.invalid/" 2>/dev/null
kill "$PX" 2>/dev/null; wait "$PX" 2>/dev/null
grep -q '^deny denied.invalid:443$' "$D/proxy.log" && echo "ok    host not in the allowlist is refused" || { echo "FAIL  denied host"; fail=1; }
# an allowlisted host gets past the allowlist and fails at DNS (offline-safe), so an "error" line proves it was tried
{ grep -q '^error ' "$D/proxy.log" && ! grep -q '^deny allowed.invalid' "$D/proxy.log"; } && echo "ok    allowlisted host is let through" || { echo "FAIL  allowlisted host"; fail=1; }
grep -q '^deny non-CONNECT$' "$D/proxy.log" && echo "ok    plain HTTP is refused" || { echo "FAIL  non-CONNECT"; fail=1; }
echo "== allowlist-proxy.py (allow-all line and blocks)"
printf 'api.example.com\n' > "$D/exact.txt"; printf '*\n!bad.example\n!*.evil.example\n# c\n' > "$D/all.txt"; printf '*\nkeep.example\n!keep.example\n' > "$D/both.txt"
H=$H D=$D python3 -I - <<'PY' || fail=1
import importlib.util, os
spec = importlib.util.spec_from_file_location("ap_all", os.path.join(os.environ["H"], "allowlist-proxy.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def check(file, host, want):
    m.ALLOW = os.path.join(os.environ["D"], file)
    got = m.allowed(host)
    assert got is want, f"{file} {host}: {got} != {want}"
check("exact.txt", "api.example.com", True); check("exact.txt", "other.example", False)   # unchanged: exact names only
check("all.txt", "anything.example", True); check("all.txt", "", False)
check("all.txt", "bad.example", False); check("all.txt", "x.bad.example", True)           # a plain block is that host only
check("all.txt", "evil.example", False); check("all.txt", "a.b.evil.example", False); check("all.txt", "notevil.example", True)
check("both.txt", "keep.example", False)                                                   # a block beats an exact allow
print("ok    allow-all, blocks (host and domain), and exact lists behave")
PY
echo "== allowlist-proxy.py (upstream lookup cache, fake DNS and dial)"
H=$H python3 -I - <<'PY' || fail=1
import importlib.util, os, socket, time
spec = importlib.util.spec_from_file_location("ap_dns", os.path.join(os.environ["H"], "allowlist-proxy.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
bad = 0
def check(name, ok, detail=""):
    global bad
    print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f"   [{detail}]"))
    bad += not ok
ADDR = {"api.example.com": "160.79.104.10", "lan.example.com": "10.0.0.7", "other.example.com": "104.18.1.1"}
lookups, dials, fail_dial = [], [], []
def fake_getaddrinfo(host, port, *a, **kw):
    lookups.append(host)
    if host not in ADDR: raise socket.gaierror("no such host")
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ADDR[host], port))]
def fake_create_connection(addr, timeout=None):
    dials.append(addr)
    if fail_dial: fail_dial.pop(); raise ConnectionRefusedError("refused")
    return object()
socket.getaddrinfo, socket.create_connection = fake_getaddrinfo, fake_create_connection
ttl = getattr(m, "DNS_TTL", None)
for _ in range(3): m.connect_upstream("api.example.com")
check("three tunnels to one host resolve it once and dial it three times", lookups.count("api.example.com") == 1 and len(dials) == 3, f"lookups={lookups} dials={dials}")
lookups.clear(); m.connect_upstream("other.example.com")
check("another host gets its own lookup", lookups == ["other.example.com"] and dials[-1] == ("104.18.1.1", 443), f"lookups={lookups} dials={dials[-1:]}")
lookups.clear(); refused = 0
for _ in range(2):
    try: m.connect_upstream("lan.example.com")
    except OSError as e: refused += "no public address" in str(e)
check("a host resolving to a LAN address is refused on every tunnel, cached or not", refused == 2, f"refused={refused}")
lookups.clear(); fail_dial.append(True)
try: m.connect_upstream("api.example.com")
except OSError: pass
m.connect_upstream("api.example.com")
check("a failed dial drops the cached answer, so the next tunnel looks the host up again", lookups.count("api.example.com") == 1, f"lookups={lookups}")
if ttl is not None:
    m.DNS_TTL = 0.2; m.connect_upstream("other.example.com"); lookups.clear()
    m.connect_upstream("other.example.com"); hit = lookups.count("other.example.com")
    time.sleep(0.3); m.connect_upstream("other.example.com")
    check("an answer is reused inside DNS_TTL and looked up again after it", hit == 0 and lookups.count("other.example.com") == 1, f"lookups={lookups}")
    m.DNS_TTL = ttl
check("DNS_TTL is set (PROXY_DNS_TTL) and by default 0 < TTL <= 120 s", isinstance(ttl, (int, float)) and 0 < ttl <= 120, f"DNS_TTL={ttl}")
raise SystemExit(1 if bad else 0)
PY
echo "== install-proxy.sh (instances, stub systemctl)"
mkdir -p "$D/ip/bin"; printf '#!/bin/sh\nexit 1\n' > "$D/ip/bin/systemctl"; chmod +x "$D/ip/bin/systemctl"
ipx() { PATH=$D/ip/bin:$PATH XDG_CONFIG_HOME=$D/ip/cfg bash "$H/install-proxy.sh" "$D/ip/px" "$@" 2>&1; }
ipx >/dev/null
U=$D/ip/cfg/systemd/user
grep -q 'Environment=PROXY_PORT=8888' "$U/sandbox-allowlist-proxy.service" && echo "ok    default install keeps port 8888" || { echo "FAIL  default unit"; fail=1; }
PROXY_INSTANCE=llama PROXY_PORT=8889 ipx >/dev/null
{ grep -q 'Environment=PROXY_PORT=8889' "$U/sandbox-allowlist-proxy-llama.service" && grep -q "PROXY_ALLOWLIST=$D/ip/px/allowlist-llama.txt" "$U/sandbox-allowlist-proxy-llama.service" && [ -e "$D/ip/px/allowlist-llama.txt" ]; } \
  && echo "ok    an instance gets its own port, allowlist and unit" || { echo "FAIL  instance unit"; fail=1; }
r=$(PROXY_INSTANCE=a/b PROXY_PORT=8890 ipx); grep -q 'may hold letters' <<<"$r" && echo "ok    a bad instance name is refused" || { echo "FAIL  instance name: $r"; fail=1; }
r=$(PROXY_INSTANCE=x ipx); grep -q 'own PROXY_PORT' <<<"$r" && echo "ok    an instance without a port is refused" || { echo "FAIL  instance port: $r"; fail=1; }
r=$(PROXY_INSTANCE=dup PROXY_PORT=8889 ipx); grep -q 'already used' <<<"$r" && [ ! -e "$U/sandbox-allowlist-proxy-dup.service" ] && echo "ok    a port already in use is refused" || { echo "FAIL  port clash: $r"; fail=1; }
echo "== new-agent.sh"
mkdir -p "$D/nb/bin" "$D/np"
printf 'NAME=tnew\nROOT=%s\nROOT_MODE=ro\nNET=proxy\nPROXY_ADDR=127.0.0.1:1\nBLANK=( )\n' "$D/proj" > "$D/np/profile"
na=$(SANDBOX_BASE=$D/nb SANDBOX_BIN=$D/nb/bin HOME=$D/nb XDG_CONFIG_HOME=$D/nb/.config bash "$H/new-agent.sh" tnew "$D/np/profile" 2>&1)
[ "$(jq -r '.env.ENABLE_CLAUDEAI_MCP_SERVERS' "$D/nb/tnew/home/settings.json")" = false ] && echo "ok    new agent gets the client env" || { echo "FAIL  new-agent client env"; fail=1; }
[ -x "$D/nb/runner/start-agents.sh" ] && [ -x "$D/nb/runner/restart-agents.sh" ] && echo "ok    new-agent installs start-agents.sh and restart-agents.sh beside the runner" || { echo "FAIL  start/restart helpers not installed"; fail=1; }
grep -q 'nothing listens on 127.0.0.1:1' <<<"$na" && echo "ok    says so when no proxy is listening" || { echo "FAIL  proxy hint: $na"; fail=1; }
# ALLOW_MESSAGING in the profile persists: a re-run with no environment variable must not re-apply the block
mkdir -p "$D/np2"
printf 'NAME=tmsg\nROOT=%s\nROOT_MODE=ro\nNET=none\nALLOW_MESSAGING=1\nBLANK=( )\n' "$D/proj" > "$D/np2/profile"
SANDBOX_BASE=$D/nb SANDBOX_BIN=$D/nb/bin HOME=$D/nb XDG_CONFIG_HOME=$D/nb/.config bash "$H/new-agent.sh" tmsg "$D/np2/profile" >/dev/null 2>&1
SANDBOX_BASE=$D/nb SANDBOX_BIN=$D/nb/bin HOME=$D/nb XDG_CONFIG_HOME=$D/nb/.config bash "$H/new-agent.sh" tmsg "$D/np2/profile" >/dev/null 2>&1
mj="$D/nb/tmsg/home/settings.json"
[ "$(jq -r 'has("crossSessionInbound")' "$mj")" = false ] && [ "$(jq -r '.permissions.deny // [] | length' "$mj")" = 0 ] \
  && echo "ok    ALLOW_MESSAGING in the profile survives a re-run" || { echo "FAIL  profile allow not honoured: $(jq -c '[.crossSessionInbound,.permissions.deny]' "$mj")"; fail=1; }
echo "== allowlist-proxy.py (in process)"
PROXY_ALLOWLIST=$D/allow.txt H=$H python3 -I - <<'PY' || fail=1
import importlib.util, os, socket, sys, threading
spec = importlib.util.spec_from_file_location("ap", os.path.join(os.environ["H"], "allowlist-proxy.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
bad = 0
def run(raw):
    cp, ct = socket.socketpair(); up, ut = socket.socketpair()
    m.connect_upstream = lambda host: up
    t = threading.Thread(target=m.handle, args=(cp,), daemon=True); t.start()
    ct.sendall(raw); ct.settimeout(3)
    resp = ct.recv(4096); got = b""
    if resp.startswith(b"HTTP/1.1 200"):
        ut.settimeout(3)
        try: got = ut.recv(4096)
        except socket.timeout: pass
        ct.close()
    t.join(5)
    return resp, got
def check(name, ok):
    global bad
    print(("ok    " if ok else "FAIL  ") + name)
    bad += not ok
resp, _ = run(b"CONNECT :443 HTTP/1.1\r\n\r\n")
check("an empty host is refused (blank allowlist lines are not names)", resp.startswith(b"HTTP/1.1 403"))
resp, got = run(b"CONNECT allowed.invalid:443 HTTP/1.1\r\n\r\n\x16\x03\x01HELLO")
check("bytes pipelined after CONNECT reach the upstream", resp.startswith(b"HTTP/1.1 200") and got == b"\x16\x03\x01HELLO")
check("a loopback address is not public", not m.is_public("127.0.0.1") and not m.is_public("10.0.0.1") and not m.is_public("169.254.1.1") and m.is_public("8.8.8.8"))
# one listed plain-HTTP request: forwarded rebuilt; anything else on the same address is refused
import http.server, tempfile
class H(http.server.BaseHTTPRequestHandler):
    seen = []
    def do_GET(self):
        H.seen.append((self.path, self.headers.get("X-Evil")))
        body = b'{"data":[]}'
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    do_POST = do_GET
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
tf = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
tf.write(f"# one endpoint\nGET http://127.0.0.1:{port}/v1/models   # models list\n"); tf.close()
m.ALLOW = tf.name
def http_req(raw):
    cp, ct = socket.socketpair()
    t = threading.Thread(target=m.handle, args=(cp,), daemon=True); t.start()
    ct.sendall(raw); ct.settimeout(5)
    out = b""
    try:
        while True:
            d = ct.recv(4096)
            if not d: break
            out += d
    except socket.timeout: pass
    t.join(5); return out
u = f"http://127.0.0.1:{port}"
r = http_req(f"GET {u}/v1/models HTTP/1.1\r\nHost: x\r\nX-Evil: 1\r\n\r\n".encode())
check("a listed GET is forwarded and answered", b'{"data":[]}' in r and r.startswith(b"HTTP/1."))
check("the client's own headers are not forwarded", H.seen == [("/v1/models", None)])
n = len(H.seen)
for name, raw in [("another path", f"GET {u}/v1/chat/completions HTTP/1.1\r\n\r\n"),
                  ("a query string", f"GET {u}/v1/models?x=1 HTTP/1.1\r\n\r\n"),
                  ("another method", f"POST {u}/v1/models HTTP/1.1\r\n\r\n"),
                  ("HEAD of a GET line", f"HEAD {u}/v1/models HTTP/1.1\r\n\r\n"),
                  ("another port", f"GET http://127.0.0.1:{port+1}/v1/models HTTP/1.1\r\n\r\n"),
                  ("another host name", f"GET http://localhost:{port}/v1/models HTTP/1.1\r\n\r\n"),
                  ("a CONNECT to the same address", f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n")]:
    r = http_req(raw.encode())
    check(f"{name} is refused", (r.startswith(b"HTTP/1.1 405") or r.startswith(b"HTTP/1.1 403")) and len(H.seen) == n)
srv.shutdown()
sys.exit(1 if bad else 0)
PY
echo "== inspect.sh"
out=$(bash "$H/inspect.sh" "$D/proj")
for want in "BLANK: .env" "BLANK: id.pem" "MAYBE: data" "ASK: "; do
  grep -q "$want" <<<"$out" && echo "ok    finds '$want'" || { echo "FAIL  missing '$want'"; fail=1; }
done
echo "== no secrets leak through blank"
out=$(bash "$H/sandbox.sh" "$D/p" run -- sh -c "cat '$D/proj/.env' '$D/proj/id.pem'; ls '$D/proj/data'")
[ -z "$out" ] && echo "ok    blank files and dirs are empty" || { echo "FAIL  got: $out"; fail=1; }
echo "== protect-config.sh"
mkdir -p "$D/cfg/.probe-agent"
# seeded with a Write rule as an earlier version of protect-config.sh wrote it: Claude Code ignores Write
# ask rules (only Edit rules are matched) and reports them as errors, so they must be dropped
stale="Write(/$(cd "$D/cfg/.probe-agent" && pwd -P)/*)"
bare="Edit(/$(cd "$D/cfg/.probe-agent" && pwd -P)/*)"   # the previous version's rule: it also matched projects/**/memory
printf '{"theme":"dark","permissions":{"allow":["Bash(ls)"],"ask":["%s","%s","Bash(rm:*)"]}}\n' "$stale" "$bare" > "$D/cfg/.probe-agent/settings.json"
bash "$H/protect-config.sh" "$D/cfg/.probe-agent" >/dev/null; bash "$H/protect-config.sh" "$D/cfg/.probe-agent" >/dev/null
sj="$D/cfg/.probe-agent/settings.json"
python3 -I -m json.tool "$sj" >/dev/null && echo "ok    settings.json is valid" || { echo "FAIL  invalid json"; fail=1; }
[ "$(jq '[.permissions.ask[]|select(startswith("Edit("))]|length' "$sj")" = 9 ] && echo "ok    9 Edit ask rules, idempotent" || { echo "FAIL  Edit ask rules"; fail=1; }
[ "$(jq '[.permissions.ask[]|select(startswith("Edit(") and endswith("/*)"))]|length' "$sj")" = 0 ] && echo "ok    no bare /* Edit rule (stale one dropped; memory stays writable)" || { echo "FAIL  bare Edit rule remains"; fail=1; }
# match real paths against the generated rules with git's own gitignore matcher (Claude Code matches like gitignore)
cfgp=$(cd "$D/cfg/.probe-agent" && pwd -P); gi="$D/gi"; rm -rf "$gi"; git init -q "$gi"
jq -r '.permissions.ask[]|select(startswith("Edit("))' "$sj" | sed -E "s#^Edit\(/$cfgp/#/#; s#\)\$##" > "$gi/.gitignore"
for pth in settings.json .claude.json skills/x/a.md rules/a.md output-styles/s.md agents/a.md hooks/h.sh; do
  git -C "$gi" check-ignore -q --no-index "$pth" && echo "ok    asks: $pth" || { echo "FAIL  not asked: $pth"; fail=1; }
done
for pth in projects/-x/memory/f.md projects/-x.y/memory/MEMORY.md backups/b state/s sessions/s.jsonl; do
  git -C "$gi" check-ignore -q --no-index "$pth" && { echo "FAIL  asks (should be free): $pth"; fail=1; } || echo "ok    free: $pth"
done
[ "$(jq '[.permissions.ask[]|select(startswith("Write("))]|length' "$sj")" = 0 ] && echo "ok    no Write ask rules (stale one dropped)" || { echo "FAIL  Write ask rules remain"; fail=1; }
[ "$(jq -r '.permissions.ask|index("Bash(rm:*)")!=null' "$sj")" = true ] && echo "ok    user's own ask rule kept" || { echo "FAIL  user ask rule lost"; fail=1; }
[ "$(jq -r '.theme,.permissions.allow[0]' "$sj" | paste -sd,)" = "dark,Bash(ls)" ] && echo "ok    existing settings kept" || { echo "FAIL  merge"; fail=1; }
[ "$(jq '.hooks.PreToolUse|length' "$sj")" = 1 ] && echo "ok    one hook after two runs" || { echo "FAIL  hook count"; fail=1; }
hook=$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$sj")
asks=$(echo '{"tool_input":{"command":"sed -i s/a/b/ /x/.probe-agent/settings.json"},"transcript_path":"/x/.probe-agent/t.jsonl"}' | bash -c "$hook")
quiet=$(echo '{"tool_input":{"command":"ls /etc/app"},"transcript_path":"/x/.probe-agent/t.jsonl"}' | bash -c "$hook")
# the hook is rebuilt with an explicit extra state dir; each row is "ask|silent<TAB>command"
echo 'STATE_DIRS=(foo-state)' > "$D/cfg/profile"   # read from the profile beside the config dir, not the environment
bash "$H/protect-config.sh" "$D/cfg/.probe-agent" >/dev/null
hook=$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$sj")
[ "$(jq '.hooks.PreToolUse|length' "$sj")" = 1 ] && echo "ok    re-run upgrades the hook in place (still one)" || { echo "FAIL  hook duplicated"; fail=1; }
hk() { printf '%s' "{\"tool_input\":{\"command\":$(jq -Rn --arg c "$2" '$c')}}" | bash -c "$hook" | grep -q ask && got=ask || got=silent
       [ "$got" = "$1" ] && echo "ok    hook $1: $2" || { echo "FAIL  hook should be $1, was $got: $2"; fail=1; }; }
P=/x/.probe-agent
hk silent "log Backup: $P/state/snap and $P/foo-state/s and $P/projects/p/memory/a.md"
hk ask "cat > $P/settings.json"
hk ask "cat > $P/state/../plugins/p"
hk ask "cat > $P/backups/../skills/x.md"
hk ask "cat > $P/foo-state/../tools/bin/x"
hk ask "cat > $P/other-state/tools/bin/x"
hk ask "cd $P/state && cat > ../skills/x.md"
hk ask "ln -s .. $P/state/up"
hk ask "ln -s skills $P/state/up"
hk ask "python3 -c \"import os; os.symlink('/x', '$P/state/u')\""
hk silent "echo three dots ... $P/state/x"
# the profile is parsed, not executed; the environment wins over the profile
printf 'touch %s/SOURCED\nSTATE_DIRS=(foo-state)   # comment\n' "$D" > "$D/cfg/profile"
bash "$H/protect-config.sh" "$D/cfg/.probe-agent" >/dev/null
[ ! -e "$D/SOURCED" ] && echo "ok    profile next to the config dir is not executed" || { echo "FAIL  profile was sourced"; fail=1; }
jq -r '.hooks.PreToolUse[0].hooks[0].command' "$sj" | grep -q 'foo.\?-state' && echo "ok    STATE_DIRS read from the profile line (comment ignored)" || { echo "FAIL  STATE_DIRS not parsed"; fail=1; }
printf 'STATE_DIRS="foo-state"\n' > "$D/cfg/profile"
warn=$(bash "$H/protect-config.sh" "$D/cfg/.probe-agent" 2>&1 >/dev/null)
grep -q "not a single-line array" <<<"$warn" && echo "ok    an unparsed STATE_DIRS line in the profile warns" || { echo "FAIL  no warning for unparsed STATE_DIRS"; fail=1; }
printf 'touch %s/SOURCED\nSTATE_DIRS=(foo-state)   # comment\n' "$D" > "$D/cfg/profile"
STATE_DIRS="env-state" bash "$H/protect-config.sh" "$D/cfg/.probe-agent" >/dev/null
jq -r '.hooks.PreToolUse[0].hooks[0].command' "$sj" | grep -q 'env.\?-state' && ! jq -r '.hooks.PreToolUse[0].hooks[0].command' "$sj" | grep -q 'foo.\?-state' && echo "ok    environment STATE_DIRS wins over the profile" || { echo "FAIL  environment should win"; fail=1; }
bash "$H/protect-config.sh" "$D/cfg/.probe-agent" >/dev/null
# an older hook (no blanking) is replaced, not duplicated
jq '.hooks.PreToolUse[0].hooks[0].command="old Claude config - needs your approval"' "$sj" > "$sj.n" && mv "$sj.n" "$sj"
bash "$H/protect-config.sh" "$D/cfg/.probe-agent" >/dev/null
jq -e '(.hooks.PreToolUse|length)==1 and (.hooks.PreToolUse[0].hooks[0].command|contains("sed -E"))' "$sj" >/dev/null && echo "ok    old hook command upgraded in place" || { echo "FAIL  old hook not upgraded"; fail=1; }
grep -q '"permissionDecision":"ask"' <<<"$asks" && echo "ok    hook asks for a command that names the config" || { echo "FAIL  hook should ask"; fail=1; }
[ -z "$quiet" ] && echo "ok    hook is silent for routine commands (transcript_path ignored)" || { echo "FAIL  hook too noisy"; fail=1; }
echo "== SHARE_PID: the host's processes, for a permissive host-administering agent"
hostnet=$(readlink /proc/self/ns/net)
for net in none host; do
  printf 'NAME=tpid%s\nROOT=%s\nROOT_MODE=ro\nNET=%s\nAGENT_HOME=%s\nSHARE_PID=1\n' "$net" "$D/proj" "$net" "$D/agent-pid-$net" > "$D/ppid-$net"
done
bash "$H/sandbox.sh" "$D/ppid-none" run -- sh -c "test -d /proc/$$" >/dev/null 2>&1 && echo "ok    SHARE_PID=1 sees a host process" || { echo "FAIL  SHARE_PID=1 cannot see host pid $$"; fail=1; }
bash "$H/sandbox.sh" "$D/p" run -- sh -c "test -d /proc/$$" >/dev/null 2>&1 && { echo "FAIL  the default still sees host pid $$"; fail=1; } || echo "ok    without SHARE_PID a host process is not visible"
inner=$(bash "$H/sandbox.sh" "$D/ppid-none" run -- readlink /proc/self/ns/net 2>&1)
[ -n "$inner" ] && [ "$inner" != "$hostnet" ] && echo "ok    SHARE_PID=1 with NET=none keeps its own network" || { echo "FAIL  SHARE_PID=1 NET=none network: $inner"; fail=1; }
inner=$(bash "$H/sandbox.sh" "$D/ppid-host" run -- readlink /proc/self/ns/net 2>&1)
[ "$inner" = "$hostnet" ] && echo "ok    SHARE_PID=1 with NET=host shares the network" || { echo "FAIL  SHARE_PID=1 NET=host network: $inner"; fail=1; }
bash "$H/sandbox.sh" "$D/ppid-none" run -- sh -c "touch '$D/proj/pid-write-test'" >/dev/null 2>&1 && { echo "FAIL  SHARE_PID=1 lost the read-only root"; fail=1; } || echo "ok    SHARE_PID=1 keeps the other boundaries (read-only root)"
bash "$H/sandbox.sh" "$D/ppid-none" run -- bwrap --unshare-user --ro-bind / / --dev /dev --proc /proc true >/dev/null 2>&1 && echo "ok    SHARE_PID=1 can start a nested sandbox" || { echo "FAIL  SHARE_PID=1 cannot start a nested sandbox"; fail=1; }
bash "$H/sandbox.sh" "$D/ppid-none" test | tail -1 | grep -q " 0 failed" && echo "ok    SHARE_PID=1 passes its own self-test" || { echo "FAIL  SHARE_PID=1 self-test"; fail=1; }
printf 'NAME=tpidbad\nROOT=%s\nAGENT_HOME=%s\nSHARE_PID=yes\n' "$D/proj" "$D/agent-pidbad" > "$D/ppid-bad"
bash "$H/sandbox.sh" "$D/ppid-bad" run -- true 2>&1 | grep -q "SHARE_PID must be 0 or 1" && echo "ok    a bad SHARE_PID is refused" || { echo "FAIL  bad SHARE_PID not refused"; fail=1; }
[ "$fail" = 0 ] && echo "ALL PASSED" || { echo "FAILURES"; exit 1; }
