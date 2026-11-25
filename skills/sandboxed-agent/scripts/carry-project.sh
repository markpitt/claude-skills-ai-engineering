#!/usr/bin/env bash
# carry-project.sh <agent_home> <workdir>: when an agent's WORKDIR changes, move its Claude project folder (transcripts, memory,
# the remote-control pointer) to the new directory's folder, so the agent keeps them. Called by sandbox.sh `run` before the agent
# starts, so nothing is writing to the folder.
#
# Claude keys a project by its working directory, every character but [A-Za-z0-9] turned into '-'
# (/home/user/x/y -> projects/-home-user-x-y). The last WORKDIR is recorded in <agent_home>/.workdir.
#   no record             record this WORKDIR, move nothing (the first start under this script)
#   same WORKDIR          nothing to do
#   changed, old folder   moved to the new name, unless the new name already exists: then both are left as they are and it says so
#   a move that fails     exit 1, and sandbox.sh does not start the agent (it would start with no history)
set -uo pipefail
home=${1:?agent home} dir=${2:?workdir}
key() { printf '%s' "${1//[^A-Za-z0-9]/-}"; }
dir=$(realpath -e -- "$dir") || { echo "carry-project: '$2' does not exist" >&2; exit 1; }
state="$home/.workdir"
if [ -f "$state" ]; then
  old=$(cat "$state")
  if [ "$old" != "$dir" ]; then
    from="$home/projects/$(key "$old")" to="$home/projects/$(key "$dir")"
    if [ ! -d "$from" ]; then
      echo "carry-project: no project folder for $old; nothing to move"
    elif [ -e "$to" ]; then
      echo "carry-project: $to already exists; left both $from and it as they are" >&2
    else
      mv -- "$from" "$to" || { echo "carry-project: could not move $from to $to" >&2; exit 1; }
      echo "carry-project: moved $(basename "$from") to $(basename "$to")"
    fi
  fi
fi
printf '%s\n' "$dir" > "$state.tmp" && mv -- "$state.tmp" "$state" || { echo "carry-project: could not record $dir" >&2; exit 1; }
