#!/bin/sh
set -eu

read_secret() {
  secret_file=$1
  if [ ! -f "$secret_file" ] || [ -L "$secret_file" ]; then
    echo "required PostgreSQL Secret file is unavailable" >&2
    exit 66
  fi
  sed -e '${s/[[:space:]]*$//;}' "$secret_file"
}

nomosmart_password=$(read_secret "$NOMOSMART_DB_PASSWORD_FILE")
nomosmart_migration_password=$(read_secret "$NOMOSMART_MIGRATION_PASSWORD_FILE")
keycloak_password=$(read_secret "$KEYCLOAK_DB_PASSWORD_FILE")

psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=nomosmart_database="$NOMOSMART_DB" \
  --set=nomosmart_user="$NOMOSMART_DB_USER" \
  --set=nomosmart_password="$nomosmart_password" \
  --set=nomosmart_migration_user="$NOMOSMART_MIGRATION_USER" \
  --set=nomosmart_migration_password="$nomosmart_migration_password" \
  --set=keycloak_database="$KEYCLOAK_DB" \
  --set=keycloak_user="$KEYCLOAK_DB_USER" \
  --set=keycloak_password="$keycloak_password" <<-'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'nomosmart_migration_user', :'nomosmart_migration_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'nomosmart_migration_user')\gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'nomosmart_user', :'nomosmart_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'nomosmart_user')\gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'nomosmart_database', :'nomosmart_migration_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'nomosmart_database')\gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'keycloak_user', :'keycloak_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'keycloak_user')\gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'keycloak_database', :'keycloak_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'keycloak_database')\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'nomosmart_database', :'nomosmart_user')\gexec
\connect :nomosmart_database
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('ALTER SCHEMA public OWNER TO %I', :'nomosmart_migration_user')\gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'nomosmart_user')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'nomosmart_migration_user', :'nomosmart_user')\gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'nomosmart_migration_user', :'nomosmart_user')\gexec
SQL
