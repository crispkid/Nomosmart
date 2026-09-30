#!/usr/bin/env sh
set -eu
set +x

# Shared path: no privilege changes/copies; Compose supplies a private root.
secret_root=${NOMOSMART_SECRET_ROOT:-/run/secrets}
case "$secret_root" in
  /run/secrets|/run/nomosmart/secrets) ;;
  *) echo "invalid Secret root" >&2; exit 64 ;;
esac
if [ -n "${NOMOSMART_SECRET_EXPORTS:-}" ]; then
  old_ifs=$IFS
  IFS=','
  for mapping in $NOMOSMART_SECRET_EXPORTS; do
    variable=${mapping%%:*}
    source_file=${mapping#*:}
    case "$variable" in
      ''|[0-9]*|*[!A-Z0-9_]*) echo "invalid Secret export mapping" >&2; exit 64 ;;
    esac
    case "$source_file" in
      /run/secrets/*) name=${source_file#/run/secrets/} ;;
      *) echo "invalid Secret export mapping" >&2; exit 64 ;;
    esac
    case "$name" in
      ''|.|..|*[!A-Za-z0-9._-]*) echo "invalid Secret export mapping" >&2; exit 64 ;;
    esac
    secret_file="$secret_root/$name"
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

unset NOMOSMART_SECRET_EXPORTS NOMOSMART_SECRET_ROOT
exec "$@"
