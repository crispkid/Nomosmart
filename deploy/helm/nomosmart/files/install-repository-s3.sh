#!/usr/bin/env sh
# Run in the official OpenSearch image against a dedicated plugin volume.
set -eu
set +x
fail() { echo "$1" >&2; exit 64; }
[ "$(id -u)" != 0 ] || fail "plugin initialization must run as non-root"
url=${OPENSEARCH_REPOSITORY_S3_URL:?official repository-s3 URL is required}
checksum=${OPENSEARCH_REPOSITORY_S3_SHA256:?repository-s3 SHA256 is required}
case "$url" in
  https://artifacts.opensearch.org/releases/plugins/repository-s3/*/repository-s3-*.zip) ;;
  *) fail "repository-s3 must be downloaded from the official HTTPS source" ;;
esac
case "$checksum" in *[!0-9a-f]*) fail "invalid repository-s3 checksum" ;; esac
[ "${#checksum}" = 64 ] || fail "invalid repository-s3 checksum"
plugins=/usr/share/opensearch/plugins
[ -d "$plugins/opensearch-security" ] || fail "official default plugins are required"
[ ! -L "$plugins" ] || fail "plugin directory must not be a symlink"
marker="$plugins/.nomosmart-repository-s3.sha256"
if [ -e "$plugins/repository-s3" ]; then
  [ ! -L "$plugins/repository-s3" ] && [ -f "$marker" ] && [ ! -L "$marker" ] || fail "existing repository-s3 has no trusted initialization marker"
  [ "$(cat "$marker")" = "$checksum" ] || fail "plugin version changed; use a fresh dedicated plugin volume"
  [ -f "$plugins/repository-s3/plugin-descriptor.properties" ] || fail "repository-s3 installation is incomplete"
  exit 0
fi
[ ! -e "$marker" ] || fail "repository-s3 initialization is inconsistent"
temporary=$(mktemp /tmp/nomosmart-repository-s3.XXXXXXXX.zip)
trap 'rm -f "$temporary"' EXIT HUP INT TERM
curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
  --connect-timeout 15 --max-time 180 --retry 2 --max-filesize 268435456 \
  --output "$temporary" "$url"
printf '%s  %s\n' "$checksum" "$temporary" | sha256sum --check --status
/usr/share/opensearch/bin/opensearch-plugin install --batch "file://$temporary"
[ -f "$plugins/repository-s3/plugin-descriptor.properties" ] || fail "repository-s3 installation did not complete"
printf '%s\n' "$checksum" > "$marker"
chmod 0444 "$marker"
