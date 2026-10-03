#!/bin/sh
# Sourced by the official nginx entrypoint before envsubst, including on rerun.
set -eu
case "${EDGE_HTTPS_PORT:-}" in
  ''|*[!0-9]*) echo 'Invalid configured HTTPS port' >&2; exit 2 ;;
esac
test "$EDGE_HTTPS_PORT" -ge 1 && test "$EDGE_HTTPS_PORT" -le 65535
case "$NOMOSMART_PUBLIC_HOST" in
  ''|*[!a-z0-9.-]*) echo 'Invalid configured public hostname' >&2; exit 2 ;;
esac
NOMOSMART_PUBLIC_AUTHORITY="$NOMOSMART_PUBLIC_HOST"
if [ "$EDGE_HTTPS_PORT" -ne 443 ]; then
  NOMOSMART_PUBLIC_AUTHORITY="$NOMOSMART_PUBLIC_AUTHORITY:$EDGE_HTTPS_PORT"
fi
if [ "$NOMOSMART_PUBLIC_ORIGIN" != "https://$NOMOSMART_PUBLIC_AUTHORITY" ]; then
  echo 'Public origin and HTTPS port do not match; correct the configuration' >&2
  exit 2
fi
export NOMOSMART_PUBLIC_AUTHORITY NOMOSMART_PUBLIC_ORIGIN EDGE_HTTPS_PORT
