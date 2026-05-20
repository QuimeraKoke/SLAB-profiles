"""Legacy → SLAB migration helpers.

Shared connection, mapping tables, audit logger, and per-phase
importers used by `manage.py migrate_legacy_data`.

The migrator runs in phases so partial imports + re-runs are safe.
Every imported row stores its source-table provenance under
`legacy_raw["_source_table"]` + `legacy_raw["_source_pk"]`, which
also functions as the idempotency key (lookup-on-rerun).
"""
