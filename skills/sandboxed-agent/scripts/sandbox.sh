#!/usr/bin/env bash
# Run a command (normally a coding agent) in a bubblewrap sandbox described by a profile file.
# No root, no Docker socket, a tmpfs home, and the working folder mounted as the profile says.
#
#   sandbox.sh <profile> run [--] <command...>   run inside, cwd = ROOT
#   sandbox.sh <profile> shell                   interactive bash inside
#   sandbox.sh <profile> show                    print the bwrap command line (no execution)
#   sandbox.sh <profile> test                    prove the boundaries the profile promises
#
# Profile (a bash file, sourced; see references/profile.example):
#   NAME, ROOT, WORKDIR (where the agent starts: ROOT, the default, or a directory under it), ROOT_MODE=ro|rw, BLANK=(globs relative to ROOT: dirs become empty, files become empty),
#   READONLY=(globs that stay readable but not writable inside an rw root),
#   NET=host|none|proxy, PROXY_ADDR=host:port (NET=proxy), PASS_ENV=(NAMES), ENV_FILE, AGENT_HOME,
#   EXTRA_RO=("src:dst" ...), EXTRA_RW=("src:dst" ...) (a writable bind: a spool the host drains; the agent cannot replace the mount point),
#   TOOLS=(dirs added to PATH), SHARE_PID=0|1 (1: keep the host's process namespace, so `ps` and `kill` reach host processes),
#   OVERLAY=("dest|layer[|layer...]" ...) instruction layers (top first) shown read-only at their paths under dest (ROOT or a folder in it),
#   CHECKS=("0|description|command" ...)  extra tests for `test`: expect exit 0 (pass) or 1 (must fail)
set -euo pipefail

PROFILE=${1:-}; CMD=${2:-}
[ -f "$PROFILE" ] || { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
shift 2 || true

# A profile at <repo>/hosts/<host>/<agent>/profile runs only on a machine that <repo>/hosts/map lists against <host>.
HOST_DIR=$(dirname "$(dirname "$(realpath -e -- "$PROFILE")")")
HOST_MAP=$(dirname "$HOST_DIR")/map
if [ "$(basename "$(dirname "$HOST_DIR")")" = hosts ] && [ -f "$HOST_MAP" ]; then
  HOST_NAME=${SANDBOX_HOSTNAME:-$(uname -n)}
  MAPPED=$(awk -v h="$HOST_NAME" '$1 !~ /^#/ && $1 == h { print $2; exit }' "$HOST_MAP")
  [ -n "$MAPPED" ] || { echo "sandbox: hostname '$HOST_NAME' is not listed in $HOST_MAP" >&2; exit 1; }
  [ "$MAPPED" = "$(basename "$HOST_DIR")" ] || {
    echo "sandbox: hostname '$HOST_NAME' maps to hosts/$MAPPED in $HOST_MAP, not to the profile's hosts/$(basename "$HOST_DIR")" >&2; exit 1; }
fi

NAME=agent ROOT_MODE=ro NET=none PROXY_ADDR=127.0.0.1:8888 BLANK=() READONLY=() PASS_ENV=() EXTRA_RO=() EXTRA_RW=() TOOLS=() CHECKS=() OVERLAY=()
ENV_FILE="" AGENT_HOME="" ROOT="" WORKDIR="" SHARE_PID=0
# shellcheck disable=SC1090
. "$PROFILE"
[ -d "$ROOT" ] || { echo "sandbox: ROOT '$ROOT' is not a directory" >&2; exit 1; }
WORKDIR=${WORKDIR:-$ROOT}
case "$(realpath -e -- "$WORKDIR" 2>/dev/null)/" in
  "$(realpath -e -- "$ROOT")"/*) [ -d "$WORKDIR" ] ;;
  *) false ;;
esac || { echo "sandbox: WORKDIR '$WORKDIR' is not a directory under ROOT" >&2; exit 1; }
ENV_FILE=${ENV_FILE:-$(dirname "$PROFILE")/env}
AGENT_HOME=${AGENT_HOME:-$HOME/.$NAME-agent}   # where it lives on the host (any path)
AGENT_MOUNT=$HOME/.$NAME-agent                # where the agent sees it: a stable name, whatever AGENT_HOME is
case "$NET" in host|none|proxy) ;; *) echo "sandbox: NET must be host, none or proxy" >&2; exit 1 ;; esac
case "$SHARE_PID" in 0|1) ;; *) echo "sandbox: SHARE_PID must be 0 or 1" >&2; exit 1 ;; esac

BRIDGE_PID="" SOCK=""
# Ends on `return 0`: an EXIT trap's last status becomes the script's, so a false `[ -n "$SOCK" ]` made every `show` and `test` exit 1.
cleanup() { [ -n "$BRIDGE_PID" ] && kill "$BRIDGE_PID" 2>/dev/null || true; [ -n "$SOCK" ] && rm -f "$SOCK"; return 0; }
trap cleanup EXIT

# A seccomp filter for what the namespaces do not cover. AF_VSOCK is not network-namespaced (before
# Linux 6.18), so with --unshare-net a sandbox can still open a vsock to the VM host: the ChromeOS host
# under Crostini, Windows under WSL2. socket()/socketpair() with AF_VSOCK fail with EAFNOSUPPORT.
# io_uring fails with ENOSYS (callers such as libuv fall back), because IORING_OP_SOCKET creates a socket
# without the socket() syscall. Another ABI (i386 on x86_64, x32) is killed: its syscall numbers differ,
# so the checks below would not see its socket(). Built here as raw BPF so there is no libseccomp
# dependency; an unknown architecture stops the sandbox rather than running without the filter.
seccomp_fd() {
  local arch sock pair x32=0
  case "$(uname -m)" in
    x86_64)  arch=0xc000003e sock=41  pair=53  x32=1 ;;
    aarch64) arch=0xc00000b7 sock=198 pair=199 ;;
    *) echo "sandbox: no seccomp filter for $(uname -m); refusing to run without one" >&2; exit 1 ;;
  esac
  local ALLOW=0x7fff0000 KILL=0x80000000 EAFNO=$((0x00050000 | 97)) ENOSYS=$((0x00050000 | 38))
  ins() {  # one struct sock_filter, little-endian: u16 code, u8 jt, u8 jf, u32 k
    local c=$1 jt=$2 jf=$3 k=$(($4))
    printf "$(printf '\\x%02x\\x%02x\\x%02x\\x%02x\\x%02x\\x%02x\\x%02x\\x%02x' \
      $((c & 255)) $((c >> 8 & 255)) "$jt" "$jf" $((k & 255)) $((k >> 8 & 255)) $((k >> 16 & 255)) $((k >> 24 & 255)))"
  }
  local f; f=$(mktemp "${TMPDIR:-/tmp}/sandbox-seccomp.XXXXXX")
  {
    ins 0x20 0 0 4                    #  0 A = arch
    ins 0x15 1 0 "$arch"              #  1 native arch? skip the kill
    ins 0x06 0 0 "$KILL"              #  2
    ins 0x20 0 0 0                    #  3 A = syscall nr
    if [ "$x32" = 1 ]; then
      ins 0x35 0 1 0x40000000         #  4 x32 (nr >= 0x40000000)? fall to kill
      ins 0x06 0 0 "$KILL"            #  5
    else
      ins 0x15 0 0 0; ins 0x15 0 0 0  #  4-5 no-ops, so the jump offsets below are the same on every arch
    fi
    ins 0x15 3 0 "$sock"              #  6 socket     -> 10
    ins 0x15 2 0 "$pair"              #  7 socketpair -> 10
    ins 0x35 0 4 425                  #  8 nr < 425 (io_uring_setup)? allow
    ins 0x35 3 4 428                  #  9 nr >= 428? allow, else io_uring_{setup,enter,register} -> ENOSYS
    ins 0x20 0 0 16                   # 10 A = low 32 bits of args[0] (the domain)
    ins 0x15 0 1 40                   # 11 AF_VSOCK?
    ins 0x06 0 0 "$EAFNO"             # 12
    ins 0x06 0 0 "$ALLOW"             # 13
    ins 0x06 0 0 "$ENOSYS"            # 14
  } > "$f"
  exec {SECCOMP_FD}<"$f"
  rm -f "$f"
}

# OVERLAY: each layer path is mounted read-only at the same path under dest; the top layer wins.
# A folder the host lacks is mounted whole; a folder the host has is walked, so its other files stay the repository's.
# The results: OV_ARGS (bwrap mounts), OV_UNITS (mount points), OV_FILES ("layer file|path"), OV_STUBS ("f|path" or "d|path" missing on the host).
OV_ARGS=() OV_UNITS=() OV_FILES=() OV_STUBS=() OV_SUMMARY=()
overlay_fail() { echo "sandbox: OVERLAY: $*" >&2; exit 1; }
ov_kind() {  # l, d, f, x (another kind) or - (absent)
  if [ -L "$1" ]; then echo l; elif [ -d "$1" ]; then echo d; elif [ -f "$1" ]; then echo f; elif [ -e "$1" ]; then echo x; else echo -; fi
}
ov_files() {  # ov_files <path> <dir>...: the regular files of the union of dirs, top first, into OV_FILES
  local dst=$1 d f; shift
  local -A seen=()
  for d in "$@"; do
    while IFS= read -r -d '' f; do
      [ -n "${seen[$f]+x}" ] && continue
      seen[$f]=1
      [ -f "$d/$f" ] && [ ! -L "$d/$f" ] && OV_FILES+=("$d/$f|$dst/$f")
    done < <(cd "$d" && find . -mindepth 1 \( -type f -o -type l \) -printf '%P\0')
  done
  return 0
}
ov_walk() {  # ov_walk <dest> <rel> <layer>...
  local dest=$1 rel=$2; shift 2
  local -a layers=("$@") names=() provs=()
  local -A seen=()
  local L n r host top k hk i
  for L in "${layers[@]}"; do
    { [ -d "$L/$rel" ] && [ ! -L "$L/$rel" ]; } || continue
    while IFS= read -r -d '' n; do
      [ -n "${seen[$n]+x}" ] || { seen[$n]=1; names+=("$n"); }
    done < <(find "$L/$rel" -mindepth 1 -maxdepth 1 -printf '%f\0')
  done
  for n in ${names[@]+"${names[@]}"}; do
    r=${rel:+$rel/}$n host=$dest/$r provs=() top=""
    for L in "${layers[@]}"; do
      k=$(ov_kind "$L/$r")
      [ "$k" = - ] && continue
      [ -n "$top" ] || top=$k
      [ "$k" = "$top" ] || overlay_fail "$r is a $k in $L but a $top in a higher layer"
      provs+=("$L/$r")
    done
    hk=$(ov_kind "$host")
    # An empty folder on the host (a mount point left by an earlier run) holds nothing of the repository's own.
    [ "$hk" = d ] && [ -z "$(ls -A "$host")" ] && hk=e
    case $top in
      f) case $hk in f|-) ;; *) overlay_fail "$host is not a plain file on the host, but the layer has one" ;; esac
         OV_ARGS+=(--ro-bind "${provs[0]}" "$host"); OV_UNITS+=("$host"); OV_FILES+=("${provs[0]}|$host")
         [ "$hk" = - ] && OV_STUBS+=("f|$host") ;;
      d) case $hk in
           d) ov_walk "$dest" "$r" "${layers[@]}" ;;
           -|e) if [ ${#provs[@]} = 1 ]; then OV_ARGS+=(--ro-bind "${provs[0]}" "$host")
              else  # bwrap stacks --overlay-src bottom first
                for ((i = ${#provs[@]} - 1; i >= 0; i--)); do OV_ARGS+=(--overlay-src "${provs[i]}"); done
                OV_ARGS+=(--ro-overlay "$host")
              fi
              OV_UNITS+=("$host"); [ "$hk" = - ] && OV_STUBS+=("d|$host"); ov_files "$host" "${provs[@]}" ;;
           *) overlay_fail "$host is not a folder on the host, but the layer has one" ;;
         esac ;;
      l) [ "$hk" = l ] && [ "$(readlink "$host")" = "$(readlink "${provs[0]}")" ] \
           || overlay_fail "${provs[0]} is a symlink: the host must hold the same link, or not hold $(dirname "$host")" ;;
      *) overlay_fail "${provs[0]} is not a file, folder or symlink" ;;
    esac
  done
  return 0
}
overlay_plan() {
  OV_ARGS=() OV_UNITS=() OV_FILES=() OV_STUBS=() OV_SUMMARY=()
  local spec dest L d root n0; local -a parts layers dests=()
  root=$(realpath -e -- "$ROOT")
  for spec in ${OVERLAY[@]+"${OVERLAY[@]}"}; do
    IFS='|' read -r -a parts <<<"$spec"
    dest=${parts[0]%/}; layers=("${parts[@]:1}")
    [ ${#layers[@]} -gt 0 ] || overlay_fail "'$spec' names no layer"
    [ -d "$dest" ] || overlay_fail "destination '$dest' is not a folder"
    case "$(realpath -e -- "$dest")/" in "$root"/*) ;; *) overlay_fail "destination '$dest' is not ROOT or under it" ;; esac
    for d in ${dests[@]+"${dests[@]}"}; do
      case "$(realpath -e -- "$dest")/" in "$(realpath -e -- "$d")"/*) overlay_fail "destinations '$d' and '$dest' are nested" ;; esac
      case "$(realpath -e -- "$d")/" in "$(realpath -e -- "$dest")"/*) overlay_fail "destinations '$dest' and '$d' are nested" ;; esac
    done
    for L in "${layers[@]}"; do
      [ -d "$L" ] || overlay_fail "layer '$L' is not a folder"
      case "$(realpath -e -- "$L")/" in "$(realpath -e -- "$dest")"/*) overlay_fail "layer '$L' is inside its destination" ;; esac
    done
    dests+=("$dest"); n0=${#OV_UNITS[@]}
    ov_walk "$dest" "" "${layers[@]}"
    OV_SUMMARY+=("overlay $dest: $((${#OV_UNITS[@]} - n0)) read-only mounts from ${layers[*]}")
  done
  return 0
}
# A missing mount point is made on the host (bwrap cannot make one in a read-only root): an empty file or folder that stays.
overlay_stubs() {
  local s p
  for s in ${OV_STUBS[@]+"${OV_STUBS[@]}"}; do
    p=${s#?|}
    [ -e "$p" ] || [ -L "$p" ] && continue
    case $s in f\|*) : > "$p" ;; d\|*) mkdir "$p" ;; esac
  done
  return 0
}

build_args() {
  seccomp_fd
  if [ "$SHARE_PID" = 1 ]; then
    # Every namespace --unshare-all makes except pid. A new procfs needs a pid namespace of its own, so the host's /proc is bound.
    # It is bound writable: a nested sandbox writes its child's uid_map there. The kernel's own permissions still apply.
    ARGS=(--unshare-user --unshare-ipc --unshare-uts --unshare-cgroup-try)
    [ "$NET" = host ] || ARGS+=(--unshare-net)
  else
    ARGS=(--unshare-all)
    [ "$NET" = host ] && ARGS+=(--share-net)
  fi
  ARGS+=(--die-with-parent --new-session --clearenv --seccomp "$SECCOMP_FD"
        --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/sbin /sbin)
  if [ "$SHARE_PID" = 1 ]; then ARGS+=(--bind /proc /proc); else ARGS+=(--proc /proc); fi
  ARGS+=(--dev /dev --tmpfs /tmp --tmpfs /run
        --tmpfs "$HOME" --bind "$AGENT_HOME" "$AGENT_MOUNT")
  # Bind only what exists: distros differ (some have no /etc/nsswitch.conf or /etc/ca-certificates, and
  # /etc/ssl/certs may symlink into /var/lib/ca-certificates). /etc/alternatives holds only links: Debian's
  # /usr/bin/awk, editor, pager and nc point through it, and dangle without it. On Fedora-style hosts
  # /etc/ssl/openssl.cnf includes /etc/crypto-policies, and without it the openssl binary fails at startup.
  for ca in /etc/ssl /etc/crypto-policies /etc/ca-certificates /var/lib/ca-certificates /etc/hosts /etc/nsswitch.conf /etc/resolv.conf /etc/localtime /etc/alternatives; do
    [ -e "$ca" ] && ARGS+=(--ro-bind "$ca" "$ca")
  done

  # The agent binary: bind only its install dir, not the whole home.
  local claude real path_extra=""
  claude=$(command -v claude 2>/dev/null || true)
  if [ -n "$claude" ]; then
    real=$(readlink -f "$claude"); path_extra=$(dirname "$real")
    ARGS+=(--ro-bind "$path_extra" "$path_extra")
  fi

  if [ "$ROOT_MODE" = rw ]; then ARGS+=(--bind "$ROOT" "$ROOT"); else ARGS+=(--ro-bind "$ROOT" "$ROOT"); fi
  # Blank the sensitive. Later mounts sit on top of the bind above. Globs are relative to ROOT.
  local g p
  shopt -s nullglob globstar
  for g in "${BLANK[@]}"; do
    for p in "$ROOT"/$g; do
      if [ -d "$p" ]; then ARGS+=(--tmpfs "$p"); elif [ -e "$p" ]; then ARGS+=(--ro-bind "$AGENT_HOME/.empty" "$p"); fi
    done
  done
  for g in "${READONLY[@]}"; do
    for p in "$ROOT"/$g; do [ -e "$p" ] && ARGS+=(--ro-bind "$p" "$p"); done
  done
  shopt -u nullglob globstar
  overlay_plan
  ARGS+=(${OV_ARGS[@]+"${OV_ARGS[@]}"})
  local pair
  # A bind source that does not exist stops bwrap with an unhelpful error; name it. A spool is made by a host service,
  # so create the directory before the agent starts. The destination must not be under $HOME (use /run/...): the self-test
  # reads a mount below ~/.claude or ~/.config as a leak of the real home.
  for pair in "${EXTRA_RO[@]}" ${EXTRA_RW[@]+"${EXTRA_RW[@]}"}; do
    [ -e "${pair%%:*}" ] || { echo "sandbox: bind source '${pair%%:*}' does not exist; create it first" >&2; exit 1; }
  done
  for pair in "${EXTRA_RO[@]}"; do ARGS+=(--ro-bind "${pair%%:*}" "${pair##*:}"); done
  for pair in ${EXTRA_RW[@]+"${EXTRA_RW[@]}"}; do ARGS+=(--bind "${pair%%:*}" "${pair##*:}"); done

  local tools="" t
  for t in "${TOOLS[@]}"; do tools="$tools$t:"; done
  # the agent's own tools first on PATH, so routine commands do not name the config dir (see protect-config.sh)
  [ -d "$AGENT_HOME/tools/bin" ] && tools="$AGENT_MOUNT/tools/bin:$tools"
  ARGS+=(--chdir "$WORKDIR"
         --setenv HOME "$HOME" --setenv PATH "${tools}${path_extra:+$path_extra:}/usr/local/bin:/usr/bin:/bin"
         --setenv TERM "${TERM:-xterm-256color}" --setenv LANG "${LANG:-C.UTF-8}"
         --setenv CLAUDE_CONFIG_DIR "$AGENT_MOUNT" --setenv SANDBOX_NAME "$NAME" --setenv SANDBOX_ROOT "$ROOT"
         --setenv SANDBOX_NET "$NET")
  # git refuses trees with mixed owners unless told this one is fine
  ARGS+=(--setenv GIT_CONFIG_COUNT 1 --setenv GIT_CONFIG_KEY_0 safe.directory --setenv GIT_CONFIG_VALUE_0 "$ROOT")
  local v
  for v in "${PASS_ENV[@]}"; do [ -n "${!v:-}" ] && ARGS+=(--setenv "$v" "${!v}"); done
  return 0
}

# proxy mode: the sandbox has no network of its own. A unix socket is bind-mounted in and bridged
# back to a host-side allowlisting proxy (PROXY_ADDR). Inside, 127.0.0.1:3128 reaches it.
start_proxy_bridge() {
  command -v socat >/dev/null || { echo "sandbox: NET=proxy needs socat" >&2; exit 1; }
  SOCK=$(mktemp -u "${XDG_RUNTIME_DIR:-/tmp}/sandbox-$NAME.XXXXXX.sock")
  socat "UNIX-LISTEN:$SOCK,fork,mode=600" "TCP:$PROXY_ADDR" &
  BRIDGE_PID=$!
  local i; for i in 1 2 3 4 5 6 7 8 9 10; do [ -S "$SOCK" ] && break; sleep 0.1; done
  ARGS+=(--bind "$SOCK" /run/proxy.sock
         --setenv HTTP_PROXY http://127.0.0.1:3128 --setenv HTTPS_PROXY http://127.0.0.1:3128
         --setenv http_proxy http://127.0.0.1:3128 --setenv https_proxy http://127.0.0.1:3128
         --setenv NO_PROXY "" --setenv no_proxy "")
}

run() {
  mkdir -p "$AGENT_HOME"; chmod 700 "$AGENT_HOME"
  : > "$AGENT_HOME/.empty"   # an empty real file: a bound /dev/null is a nodev mount and gives "permission denied"
  # Credentials live in the env file (chmod 600), not on the command line or in the profile.
  # shellcheck disable=SC1090
  [ -f "$ENV_FILE" ] && . "$ENV_FILE"
  # A changed WORKDIR takes the agent's transcripts and memory with it (see carry-project.sh).
  bash "$(dirname "$(readlink -f "$0")")/carry-project.sh" "$AGENT_HOME" "$WORKDIR" || exit 1
  build_args
  overlay_stubs
  if [ "$NET" = proxy ]; then
    start_proxy_bridge
    # not exec: the trap must clean the bridge up
    bwrap "${ARGS[@]}" sh -c 'socat TCP-LISTEN:3128,bind=127.0.0.1,fork,reuseaddr UNIX-CONNECT:/run/proxy.sock & sleep 0.3; exec "$@"' sh "$@"
  else
    exec bwrap "${ARGS[@]}" "$@"
  fi
}

selftest() {
  local pass=0 fail=0 out rc
  t() {  # t <description> <0|1> <command...>: expect success (0) or failure (1) inside the sandbox
    local d=$1 want=$2; shift 2
    if out=$(bash "$0" "$PROFILE" run -- "$@" 2>&1); then rc=0; else rc=1; fi
    if [ "$rc" = "$want" ]; then echo "ok    $d"; pass=$((pass+1)); else echo "FAIL  $d  (rc=$rc: ${out:0:100})"; fail=$((fail+1)); fi
  }
  local probe="$ROOT/.sandbox-write-test" g p
  t "root is readable"                         0 sh -c "ls '$ROOT' >/dev/null"
  if [ "$ROOT_MODE" = rw ]; then t "root is writable (rw profile)" 0 sh -c "echo x > '$probe' && rm '$probe'"
  else                           t "root is read-only (ro profile)" 1 sh -c "touch '$probe'"; fi
  shopt -s nullglob globstar
  for g in "${BLANK[@]}"; do
    for p in "$ROOT"/$g; do
      if [ -d "$p" ]; then t "blank dir  ${p#$ROOT/}" 0 sh -c "test -z \"\$(ls -A '$p')\""
      elif [ -e "$p" ]; then t "blank file ${p#$ROOT/}" 0 sh -c "test ! -s '$p'"; fi
    done
  done
  shopt -u nullglob globstar
  t "no docker socket"                         1 sh -c "test -e /var/run/docker.sock"
  # A ROOT that is, or sits below, one of these (ROOT=$HOME/.claude) is mounted on purpose, so leave it out.
  # A ROOT that IS the home folder (an agent that works across every repository in it) mounts all of it on purpose, so these paths
  # exist inside; for that profile the BLANK lines above and its own CHECKS are the test, and this one is skipped with a note.
  local hp; local -a hl=()
  if [ "$(realpath -e -- "$ROOT")" = "$(realpath -e -- "$HOME")" ]; then
    echo "note  ROOT is the home folder: the blank lines above and the profile's CHECKS stand in for \"no access to the real home\""
  else
    for hp in .ssh .claude .config; do
      case "$ROOT/" in "$HOME/$hp/"*) continue ;; esac
      hl+=("$HOME/$hp")
    done
    t "no access to the real home"               1 sh -c 'for p; do test -e "$p" && exit 0; done; exit 1' _ "${hl[@]}"
  fi
  t "no /etc/shadow"                           1 sh -c "cat /etc/shadow"
  t "awk runs (alternatives links resolve)"   0 sh -c "awk 'BEGIN { exit 0 }'"
  t "root cannot be gained"                    1 sh -c "su -c true root </dev/null"
  overlay_plan
  if [ ${#OV_UNITS[@]} -gt 0 ]; then
    local s sums=""
    for s in ${OV_FILES[@]+"${OV_FILES[@]}"}; do sums+="$(sha256sum < "${s%%|*}" | cut -d' ' -f1)  ${s#*|}"$'\n'; done
    t "instruction files match their layers (${#OV_FILES[@]} files)" 0 sh -c 'printf "%s" "$1" | sha256sum -c --quiet -' _ "$sums"
    # A mount point whose last mountinfo entry is ro, in its mount or its superblock options; mountinfo writes a space as \040.
    t "instruction paths are read-only mounts (${#OV_UNITS[@]})" 0 sh -c '
      for p; do
        e=$(printf "%s" "$p" | sed "s/ /\\\\040/g") o=""
        while read -r _ _ _ _ m opts rest; do
          [ "$m" = "$e" ] || continue
          sb=" $rest"; sb=${sb#* - }; sb=${sb#* }; sb=${sb#* }; o="$opts ${sb%% *}"
        done < /proc/self/mountinfo
        case ",${o% *}, ,${o#* }," in *,ro,*) ;; *) echo "not a read-only mount: $p"; exit 1 ;; esac
      done' _ "${OV_UNITS[@]}"
  fi
  local c w d cmd
  for c in "${CHECKS[@]}"; do
    w=${c%%|*}; c=${c#*|}; d=${c%%|*}; cmd=${c#*|}
    t "$d" "$w" sh -c "$cmd"
  done
  case "$NET" in
    none)  t "no network (direct egress fails)"   1 sh -c "curl -sS --max-time 4 -o /dev/null https://example.com" ;;
    proxy) t "direct egress fails (no proxy)"     1 sh -c "curl -sS --noproxy '*' --max-time 4 -o /dev/null https://example.com"
           t "proxy bridge listens in the sandbox" 0 bash -c "exec 3<>/dev/tcp/127.0.0.1/3128" ;;
    host)  echo "note  NET=host: the network is shared with the machine (bwrap cannot filter it)" ;;
  esac
  echo "---"; echo "$pass passed, $fail failed"; [ "$fail" = 0 ]
}

case "$CMD" in
  run)   [ "${1:-}" = "--" ] && shift; [ $# -gt 0 ] || { echo "run needs a command" >&2; exit 2; }; run "$@" ;;
  shell) run bash -l ;;
  show)  build_args; [ ${#OV_SUMMARY[@]} = 0 ] || printf '%s\n' "${OV_SUMMARY[@]}"; printf 'bwrap'; printf ' %q' "${ARGS[@]}"; echo ;;
  test)  selftest ;;
  *)     sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
