#!/usr/bin/env sh
set -eu
set +x

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

unset NOMOSMART_SECRET_EXPORTS
exec "$@"
