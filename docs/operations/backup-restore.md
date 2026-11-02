# Backup and restore

**Not implemented.** No backups are taken, no restore has been tested, and no recovery objectives are set. This is a Milestone 8 gate.

Known requirements:

- A dump needs a role that sees all rows, so `pg_dump` must run with a separate BYPASSRLS maintenance role, which is the planned `aai_maint`. It must never reach an application container.
- Restore must recreate the roles first, because policies and grants name them.
- Restoring must be tested, not assumed from a completed backup.
- Audit triggers block `TRUNCATE`, so restore into an empty database rather than over an existing one.
