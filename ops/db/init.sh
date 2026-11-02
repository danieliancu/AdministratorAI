#!/bin/sh
# Runs on every `up`, not only on an empty volume, so role changes reach existing databases.
set -eu

psql -v ON_ERROR_STOP=1 -d postgres \
  -v owner_password="$AAI_OWNER_PASSWORD" \
  -v app_password="$AAI_APP_PASSWORD" \
  -v platform_password="$AAI_PLATFORM_PASSWORD" \
  -f /ops/db/roles.sql

if [ "${AAI_OWNER_CREATEDB:-false}" = "true" ]; then
  # Development and test only: the owner creates the test database.
  psql -v ON_ERROR_STOP=1 -d postgres -c "ALTER ROLE aai_owner CREATEDB"
else
  psql -v ON_ERROR_STOP=1 -d postgres -c "ALTER ROLE aai_owner NOCREATEDB"
fi

# Test databases are cloned from template1, so they inherit the extension.
psql -v ON_ERROR_STOP=1 -d template1 -c "CREATE EXTENSION IF NOT EXISTS vector"
psql -v ON_ERROR_STOP=1 -d administrator_ai -c "CREATE EXTENSION IF NOT EXISTS vector"
