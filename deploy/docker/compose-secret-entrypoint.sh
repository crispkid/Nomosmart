#!/usr/bin/env sh
# Compose-only preparation. No source path, destination or UID comes from env.
set -eu
set +x
fail() { echo "$1" >&2; exit "${2:-64}"; }
[ "$(id -u)" = 0 ] || fail "Compose preparation requires root"
[ "$#" -ge 2 ] || fail "Compose service profile and command are required"
profile=$1
shift
case "$profile" in
  backend|migration|rustfs) uid=10001; gid=10001 ;;
  postgresql)
    uid=$(id -u postgres); gid=$(id -g postgres)
    [ "$1" = docker-entrypoint.sh ] && [ "${2:-}" = postgres ] || fail "invalid PostgreSQL command"
    ;;
  *) fail "invalid Compose service profile" ;;
esac
case "$uid:$gid" in *[!0-9:]*|0:*|*:0) fail "invalid service identity" ;; esac
[ -z "${NOMOSMART_RUN_AS:-}${NOMOSMART_COPY_DIRS:-}${NOMOSMART_REMAP_SECRETS:-}" ] || fail "unsupported legacy preparation controls"
if [ "$profile" = postgresql ]; then
  # The upstream entrypoint owns PGDATA initialization and its own privilege
  # drop. Do not require the application's drop tool or bypass that entrypoint.
  command -v gosu >/dev/null 2>&1 || fail "PostgreSQL privilege-drop tool is required"
  drop=upstream
elif command -v su-exec >/dev/null 2>&1; then
  drop=su-exec
elif command -v setpriv >/dev/null 2>&1 && setpriv --help 2>&1 | grep -q -- '--reuid'; then
  drop=setpriv
elif command -v chroot >/dev/null 2>&1 && chroot --help 2>&1 | grep -q -- '--userspec'; then
  # Official Flyway/RustFS provide coreutils chroot and BusyBox setpriv. The
  # latter cannot change UID. Keep '/' fixed; use chroot only to drop identity.
  drop=chroot
else
  fail "a supported privilege-drop tool is required"
fi

private=/run/nomosmart
# A root-owned dedicated tmpfs is mandatory; never copy into a host bind mount.
[ -d /run ] && [ ! -L /run ] && [ -d "$private" ] && [ ! -L "$private" ] || fail "private runtime mount is required"
[ "$(stat -f -c %T "$private")" = tmpfs ] || fail "private runtime mount must be tmpfs"
[ "$(stat -c %u "$private")" = 0 ] || fail "invalid private runtime owner"
mountpoint -q "$private" || fail "dedicated private runtime mount is required"
chown "0:$gid" "$private"
chmod 0710 "$private"
previous_umask=$(umask)
umask 077
private_dir() {
  if [ -e "$1" ] || [ -L "$1" ]; then
    [ -d "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u "$1")" = 0 ] || fail "invalid private runtime directory"
  else
    mkdir "$1"
  fi
  # Services may traverse these directories, but cannot replace paths/symlinks.
  chown "0:$gid" "$1"
  chmod 0710 "$1"
}
private_dir "$private/secrets"
private_dir "$private/tls"
copy_file() {
  [ -f "$1" ] && [ ! -L "$1" ] && [ -s "$1" ] || fail "required private file is unavailable" 66
  if [ -e "$2" ] || [ -L "$2" ]; then
    [ -f "$2" ] && [ ! -L "$2" ] && [ "$(stat -c %u "$2")" = "$uid" ] && [ "$(stat -c %h "$2")" = 1 ] || fail "invalid private runtime file"
  fi
  cp "$1" "$2"
  chown "$uid:$gid" "$2"
  chmod 0400 "$2"
}

# Only allowlisted files actually mounted for this service are prepared.
names='app_encryption_key database_url redis_url celery_broker_url celery_result_backend s3_access_key_id rustfs_secret_access_key opensearch_service_password neo4j_service_password oidc_client_secret keycloak_sync_client_secret keycloak_bootstrap_admin_password break_glass_initial_password opensearch_admin_password neo4j_admin_password database_migration_password postgres_admin_password postgres_app_password postgres_migration_password keycloak_db_password'
[ -d /run/secrets ] && [ ! -L /run/secrets ] || fail "Secret mount is required" 66
for name in $names; do
  if [ -e "/run/secrets/$name" ] || [ -L "/run/secrets/$name" ]; then
    copy_file "/run/secrets/$name" "$private/secrets/$name"
  fi
done

# No full environment dump: only known path-valued configuration is read.
variables='APP_ENCRYPTION_KEY_FILE DATABASE_URL_FILE REDIS_URL_FILE CELERY_BROKER_URL_FILE CELERY_RESULT_BACKEND_FILE S3_ACCESS_KEY_ID_FILE S3_SECRET_ACCESS_KEY_FILE OPENSEARCH_PASSWORD_FILE NEO4J_PASSWORD_FILE OIDC_CLIENT_SECRET_FILE KEYCLOAK_SYNC_CLIENT_SECRET_FILE KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD_FILE BREAK_GLASS_INITIAL_PASSWORD_FILE OPENSEARCH_ADMIN_PASSWORD_FILE NEO4J_ADMIN_PASSWORD_FILE POSTGRES_PASSWORD_FILE NOMOSMART_DB_PASSWORD_FILE NOMOSMART_MIGRATION_PASSWORD_FILE KEYCLOAK_DB_PASSWORD_FILE'
for variable in $variables; do
  file=$(printenv "$variable" || true)
  [ -n "$file" ] || continue
  case "$file" in /run/secrets/*) name=${file#/run/secrets/} ;; *) fail "invalid Secret file reference" ;; esac
  case "$name" in ''|.|..|*[!A-Za-z0-9._-]*) fail "invalid Secret file reference" ;; esac
  [ -f "$private/secrets/$name" ] || fail "Secret file is not allowed or not mounted" 66
  export "$variable=$private/secrets/$name"
done

if [ "$profile" = backend ]; then
  # Only the API service mounts this disk volume. No arbitrary env-selected chown.
  if [ -e /var/lib/nomosmart-upload ]; then
    [ -d /var/lib/nomosmart-upload ] && [ ! -L /var/lib/nomosmart-upload ] || fail "invalid upload scratch mount"
    mountpoint -q /var/lib/nomosmart-upload || fail "upload scratch requires a dedicated disk mount"
    case "$(stat -f -c %T /var/lib/nomosmart-upload)" in tmpfs|ramfs) fail "upload scratch must not use memory-backed storage" ;; esac
    chown "0:$gid" /var/lib/nomosmart-upload
    chmod 0770 /var/lib/nomosmart-upload
  fi
  for parent in /etc/nomosmart /etc/nomosmart/tls; do
    [ -d "$parent" ] && [ ! -L "$parent" ] || fail "TLS mount is required" 66
  done
  for name in rustfs-ca.crt opensearch-ca.crt; do
    copy_file "/etc/nomosmart/tls/$name" "$private/tls/$name"
  done
  for variable in S3_CA_CERT_PATH OPENSEARCH_CA_CERT_PATH; do
    file=$(printenv "$variable" || true)
    case "$file" in
      /etc/nomosmart/tls/rustfs-ca.crt|/etc/nomosmart/tls/opensearch-ca.crt)
        export "$variable=$private/tls/${file##*/}" ;;
      '') ;;
      *) fail "unsupported Compose CA reference" ;;
    esac
  done
  export COMPOSE_SECRET_MOUNT_ROOT="$private/secrets"
elif [ "$profile" = rustfs ]; then
  [ -d /opt/rustfs-tls ] && [ ! -L /opt/rustfs-tls ] || fail "TLS mount is required" 66
  for name in rustfs_cert.pem rustfs_key.pem rustfs_ca.pem; do
    copy_file "/opt/rustfs-tls/$name" "$private/tls/$name"
  done
  export RUSTFS_TLS_PATH="$private/tls"
fi
umask "$previous_umask"
export NOMOSMART_SECRET_ROOT="$private/secrets"
if [ "$profile" = postgresql ]; then
  # Upstream initializes PGDATA as root, then drops to postgres itself.
  exec /opt/nomosmart/secret-env-entrypoint.sh "$@"
elif [ "$drop" = su-exec ]; then
  exec su-exec "$uid:$gid" /opt/nomosmart/secret-env-entrypoint.sh "$@"
elif [ "$drop" = chroot ]; then
  exec chroot --userspec="$uid:$gid" --groups="$gid" / /opt/nomosmart/secret-env-entrypoint.sh "$@"
else
  exec setpriv --reuid="$uid" --regid="$gid" --clear-groups -- /opt/nomosmart/secret-env-entrypoint.sh "$@"
fi
