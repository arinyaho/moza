# Source from .bashrc:  source <moza-repo>/shell/moza.bash

moza-use() {
  if [[ -z "$1" ]]; then
    echo "usage: moza-use <profile>" >&2
    return 2
  fi
  local exports
  exports="$(command moza use "$1")" || return $?
  eval "$exports"
}

moza-unset() {
  local clears
  clears="$(command moza unset)" || return $?
  eval "$clears"
}

__moza_atexit() {
  if [[ -n "$MOZA_PROFILE" ]]; then
    command moza doctor --gc >/dev/null 2>&1 || true
  fi
}

trap __moza_atexit EXIT
