#!/bin/sh
# Runs once, when the Postgres volume is first initialised. Creates the role the API connects
# as: it can log in but is not a superuser, does not own tables and cannot bypass row-level
# security. Migrations (run as POSTGRES_USER) grant it table privileges.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v app_password="$AUREVIA_APP_DB_PASSWORD" <<'SQL'
CREATE ROLE aurevia_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
    PASSWORD :'app_password';
SQL
