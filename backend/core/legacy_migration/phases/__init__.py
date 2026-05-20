"""Per-phase importers for the legacy migrator.

Each phase exposes a `run(ctx)` function that takes the shared
`MigrationContext` (legacy DB connection, audit log, dry_run flag,
date scope, club + dept resolver) and runs the import for one entity.

Phases:
    phase0_reference  — Category, Position
    phase1_players    — Player (with photo copy)
    phase2_contracts  — Contract
    phase3_events     — Event (matches)
    phase4_callups    — EventParticipant (citaciones + estadistica_interna)
    phase5_episodes   — Episode + ExamResult(lesiones)
    phase6_results    — All other ExamResult imports

Run them via `manage.py migrate_legacy_data --entities=phase0,phase1,...`.
"""
