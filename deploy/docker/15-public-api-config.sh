#!/bin/sh
# Runs before the official nginx image's template envsubst step.
set -eu
# Compose supplies defaults. Do not default inside this child process: its
# exports cannot configure the later envsubst process, and empty values are bad.
: "${BACKEND_EDGE_UPSTREAM?Missing BACKEND_EDGE_UPSTREAM}"
: "${PUBLIC_API_READ_TIMEOUT_SECONDS?Missing PUBLIC_API_READ_TIMEOUT_SECONDS}"

fail() { printf '%s\n' "Invalid public API edge configuration: $1" >&2; exit 1; }
# Internal Compose HTTP origin only, no credentials, paths, query or directives.
# TLS terminates at the existing edge; this does not disable upstream TLS checks.
[ "$BACKEND_EDGE_UPSTREAM" = "$(printf '%s' "$BACKEND_EDGE_UPSTREAM" | tr -d '\r\n')" ] || fail BACKEND_EDGE_UPSTREAM
printf '%s\n' "$BACKEND_EDGE_UPSTREAM" | grep -Eq '^http://([A-Za-z0-9][A-Za-z0-9.-]*|\[[0-9A-Fa-f:]+\])(:[0-9]{1,5})?$' || fail BACKEND_EDGE_UPSTREAM
case "$BACKEND_EDGE_UPSTREAM" in
  *]:*) port=${BACKEND_EDGE_UPSTREAM##*:} ;;
  *]) port=80 ;;
  *) authority=${BACKEND_EDGE_UPSTREAM#http://}; port=${authority##*:}; [ "$port" != "$authority" ] || port=80 ;;
esac
case "$port" in 0*|*[!0-9]*) fail BACKEND_EDGE_UPSTREAM ;; esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || fail BACKEND_EDGE_UPSTREAM
case "$PUBLIC_API_READ_TIMEOUT_SECONDS" in ''|0*|*[!0-9]*|?????*) fail PUBLIC_API_READ_TIMEOUT_SECONDS ;; esac
[ "$PUBLIC_API_READ_TIMEOUT_SECONDS" -ge 1 ] && [ "$PUBLIC_API_READ_TIMEOUT_SECONDS" -le 3600 ] || fail PUBLIC_API_READ_TIMEOUT_SECONDS
