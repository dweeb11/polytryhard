# Per-Environment Migrations

Per-environment databases hold environment-specific ledgers, signals, and audit
state. They may be rebuilt from shared data when a milestone explicitly allows
it, but append-only audit discipline still applies.
