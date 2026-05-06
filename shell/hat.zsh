# Source from .zshrc:  source <hat-repo>/shell/hat.zsh

hat-use() {
  if [[ -z "$1" ]]; then
    echo "usage: hat-use <profile>" >&2
    return 2
  fi
  local exports
  exports="$(command hat use "$1")" || return $?
  eval "$exports"
}

hat-unset() {
  local clears
  clears="$(command hat unset)" || return $?
  eval "$clears"
}

__hat_atexit() {
  if [[ -n "$HAT_PROFILE" ]]; then
    command hat doctor --gc >/dev/null 2>&1 || true
  fi
}

trap __hat_atexit EXIT
