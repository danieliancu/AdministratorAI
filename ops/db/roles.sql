-- Idempotent role and database setup. Applied by ops/db/init.sh as the superuser.
-- Runtime roles get table access only through explicit grants in migrations;
-- there are deliberately no default privileges.

SELECT 'CREATE ROLE aai_owner LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aai_owner') \gexec
SELECT 'CREATE ROLE aai_app LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aai_app') \gexec
SELECT 'CREATE ROLE aai_platform LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aai_platform') \gexec
SELECT 'CREATE ROLE aai_platform_definer NOLOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aai_platform_definer') \gexec

ALTER ROLE aai_owner NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOREPLICATION PASSWORD :'owner_password';
ALTER ROLE aai_app NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION PASSWORD :'app_password';
ALTER ROLE aai_platform NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION PASSWORD :'platform_password';
ALTER ROLE aai_platform_definer NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION;

-- Lets migrations create objects owned by the definer. INHERIT FALSE: the owner must not
-- pick up the definer's row-level policies just by being a member.
GRANT aai_platform_definer TO aai_owner WITH INHERIT FALSE, SET TRUE;

-- A role-level timezone lets Django skip its session-level SET TIME ZONE,
-- which would not survive PgBouncer transaction pooling.
ALTER ROLE aai_owner SET timezone = 'UTC';
ALTER ROLE aai_app SET timezone = 'UTC';
ALTER ROLE aai_platform SET timezone = 'UTC';

ALTER ROLE aai_app SET statement_timeout = '30s';
ALTER ROLE aai_app SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE aai_platform SET statement_timeout = '30s';
ALTER ROLE aai_platform SET idle_in_transaction_session_timeout = '60s';

SELECT 'CREATE DATABASE administrator_ai OWNER aai_owner' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'administrator_ai') \gexec

REVOKE ALL ON DATABASE administrator_ai FROM PUBLIC;
GRANT CONNECT ON DATABASE administrator_ai TO aai_owner, aai_app, aai_platform;
