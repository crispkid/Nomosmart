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

# Initial normal-admin sign-in is reachable only from the deployment allowlist.
NOMOSMART_ONBOARDING_ACCESS_RULES=''
if [ "${DEPLOYMENT_PHASE:-operational}" = onboarding ]; then
  rules='allow 127.0.0.1/32;'
  policy=${ONBOARDING_ADMIN_ALLOW_CIDR:-127.0.0.1/32}
  case "$policy" in ''|*[!0-9a-fA-F:./,]*) echo 'Invalid onboarding source policy' >&2; exit 64 ;; esac
  old_ifs=$IFS
  IFS=,
  for cidr in $policy; do
    case "$cidr" in 0.0.0.0/0|::/0) echo 'Unrestricted onboarding source is forbidden' >&2; exit 64 ;; esac
    rules="$rules allow $cidr;"
  done
  IFS=$old_ifs
  NOMOSMART_ONBOARDING_ACCESS_RULES="$rules deny all;"
fi
export NOMOSMART_ONBOARDING_ACCESS_RULES
