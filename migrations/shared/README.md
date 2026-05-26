# Shared Migrations

The shared database is append-only. Migrations here may add nullable columns,
tables, or indexes, but must not destructively rename or drop persisted data
without an explicit PDD update and backfill plan.
