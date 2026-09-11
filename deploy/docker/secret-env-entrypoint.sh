#!/usr/bin/env sh
set -eu
set +x

run_as=${NOMOSMART_RUN_AS:-}

_chown_run_as() {
  path=$1
  [ -n "$run_as" ] || return 0
  uid=${run_as%%:*}
  gid=${run_as#*:}
  if [ "$gid" = "$run_as" ]; then
    gid=$uid
  fi
  chown -R "$uid:$gid" "$path"
}

_rewrite_env_prefix() {
  src=$1
  dst=$2
  env_dump=$(mktemp)
  printenv >"$env_dump"
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    name=${line%%=*}
    value=${line#*=}
    case "$value" in
    "$src" | "$src"/*)
      suffix=${value#"$src"}
      export "${name}=${dst}${suffix}"
      ;;
    esac
  done <"$env_dump"
  rm -f "$env_dump"
}

_copy_path() {
  src=$1
  dst=$2
  if [ -L "$src" ] || [ ! -e "$src" ]; then
    echo "required path is unavailable" >&2
    exit 66
  fi
  mkdir -p "$(dirname "$dst")"
  if [ -d "$src" ]; then
    rm -rf "$dst"
    mkdir -p "$dst"
    cp -a "$src"/. "$dst"/
  else
    if [ ! -f "$src" ]; then
      echo "required path is unavailable" >&2
      exit 66
    fi
    cp -a "$src" "$dst"
  fi
}

if [ -n "${NOMOSMART_SECRET_EXPORTS:-}" ]; then
  old_ifs=$IFS
  IFS=','
  for mapping in $NOMOSMART_SECRET_EXPORTS; do
    case "$mapping" in
      [A-Z_]*:/run/secrets/*) ;;
      *) echo "invalid Secret export mapping" >&2; exit 64 ;;
    esac
    variable=${mapping%%:*}
    secret_file=${mapping#*:}
    if [ ! -f "$secret_file" ] || [ -L "$secret_file" ]; then
      echo "required Secret file is unavailable" >&2
      exit 66
    fi
    value=$(sed -e '${s/[[:space:]]*$//;}' "$secret_file")
    if [ -z "$value" ]; then
      echo "required Secret file is empty" >&2
      exit 65
    fi
    export "$variable=$value"
    unset value
  done
  IFS=$old_ifs
fi

remap_secrets=0
if [ -n "$run_as" ] || [ "${NOMOSMART_REMAP_SECRETS:-}" = "1" ]; then
  remap_secrets=1
fi

if [ "$remap_secrets" = 1 ] && [ -d /run/secrets ]; then
  mkdir -p /run/nomosmart/secrets
  umask 077
  for secret_file in /run/secrets/*; do
    [ -e "$secret_file" ] || continue
    if [ -L "$secret_file" ] || [ ! -f "$secret_file" ]; then
      echo "required Secret file is unavailable" >&2
      exit 66
    fi
    base=${secret_file##*/}
    cp "$secret_file" "/run/nomosmart/secrets/$base"
    if [ -n "$run_as" ]; then
      chmod 0400 "/run/nomosmart/secrets/$base"
    else
      chmod 0444 "/run/nomosmart/secrets/$base"
    fi
  done
  _chown_run_as /run/nomosmart/secrets
  _rewrite_env_prefix /run/secrets /run/nomosmart/secrets
fi

if [ -n "${NOMOSMART_COPY_DIRS:-}" ]; then
  old_ifs=$IFS
  IFS=','
  for mapping in $NOMOSMART_COPY_DIRS; do
    case "$mapping" in
      /*:/*) ;;
      *) echo "invalid path copy mapping" >&2; exit 64 ;;
    esac
    src=${mapping%%:*}
    dst=${mapping#*:}
    _copy_path "$src" "$dst"
    _chown_run_as "$dst"
    _rewrite_env_prefix "$src" "$dst"
  done
  IFS=$old_ifs
fi

unset NOMOSMART_SECRET_EXPORTS NOMOSMART_COPY_DIRS NOMOSMART_RUN_AS NOMOSMART_REMAP_SECRETS

if [ -n "$run_as" ]; then
  if [ "$(id -u)" -ne 0 ]; then
    echo "privilege drop requires root" >&2
    exit 64
  fi
  uid=${run_as%%:*}
  gid=${run_as#*:}
  if [ "$gid" = "$run_as" ]; then
    gid=$uid
  fi
  if command -v su-exec >/dev/null 2>&1; then
    exec su-exec "${uid}:${gid}" "$@"
  fi
  if command -v setpriv >/dev/null 2>&1 && setpriv --help 2>&1 | grep -q -- '--reuid'; then
    exec setpriv --reuid="$uid" --regid="$gid" --init-groups -- "$@"
  fi
  echo "su-exec or util-linux setpriv is required to drop privileges" >&2
  exit 64
fi

exec "$@"
