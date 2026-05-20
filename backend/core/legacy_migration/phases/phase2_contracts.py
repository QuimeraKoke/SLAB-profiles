"""Phase 2 — Contract import.

Legacy `contrato` (28 rows total, 6 in 2025+) → SLAB `Contract`.
Idempotent via legacy_raw["_source_pk"] match.

Quirk: legacy `fin_contrato` is `character varying`, not `date`. We
attempt to parse it; failures fall back to the row's `created_at` year
+ 12 months, and the raw text always lands in `legacy_raw` for audit.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction

from core.models import Contract

from ..mapping import fix_mojibake, jsonable
from .context import MigrationContext


def run(ctx: MigrationContext) -> None:
    ctx.audit.info("phase2_contracts: start")

    # Scope: only contracts whose inicio_contrato falls in the window.
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM contrato "
        " WHERE inicio_contrato >= %s AND inicio_contrato <= %s "
        " ORDER BY id",
        (ctx.date_from, ctx.date_to),
    )

    for row in rows:
        try:
            _import_one_contract(ctx, row)
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(
                phase="phase2",
                action="failed",
                source_table="contrato",
                source_pk=row.get("id"),
                reason=f"{type(exc).__name__}: {exc}",
            )

    ctx.audit.info("phase2_contracts: done", count=len(rows))


def _import_one_contract(ctx: MigrationContext, row: dict) -> None:
    legacy_id = row["id"]
    player_uuid = ctx.player_by_legacy_id.get(row.get("jugador_id"))

    if not player_uuid:
        ctx.audit.record(
            phase="phase2",
            action="skipped",
            source_table="contrato",
            source_pk=legacy_id,
            reason=f"player jugador_id={row.get('jugador_id')} not in active set",
        )
        return

    legacy_raw = jsonable({
        "_source_table": "contrato",
        "_source_pk": legacy_id,
        "_source_row": row,
    })

    existing = Contract.objects.filter(
        legacy_raw__contains={"_source_table": "contrato", "_source_pk": legacy_id},
    ).first()

    end_date = _parse_end_date(row.get("fin_contrato"), row.get("inicio_contrato"))
    ownership = _to_decimal(row.get("porcentaje_contrato")) or Decimal("1.00")
    total_bruto = _to_decimal(row.get("total_bruto"))

    fields = {
        "player_id": player_uuid,
        "start_date": row.get("inicio_contrato"),
        "end_date": end_date,
        "ownership_percentage": ownership,
        "total_gross_amount": total_bruto,
        "fixed_bonus": fix_mojibake(row.get("bono_fijo") or "") or "",
        "variable_bonus": fix_mojibake(row.get("bono_variable") or "") or "",
        "salary_increase": fix_mojibake(row.get("aumento") or "") or "",
        "purchase_option": fix_mojibake(row.get("opcion_compra") or "") or "",
        "release_clause": fix_mojibake(row.get("clausula_salida") or "") or "",
        "renewal_option": fix_mojibake(row.get("opcion_renovacion") or "") or "",
        "legacy_raw": legacy_raw,
    }

    if ctx.dry_run:
        ctx.audit.record(
            phase="phase2",
            action="updated" if existing else "created",
            source_table="contrato",
            source_pk=legacy_id,
            target_model="core.Contract",
            target_pk=str(existing.id) if existing else None,
            reason="dry-run",
        )
        return

    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        with transaction.atomic():
            existing.save()
        action = "updated"
        target_pk = str(existing.id)
    else:
        with transaction.atomic():
            contract = Contract.objects.create(**fields)
        action = "created"
        target_pk = str(contract.id)

    ctx.audit.record(
        phase="phase2",
        action=action,
        source_table="contrato",
        source_pk=legacy_id,
        target_model="core.Contract",
        target_pk=target_pk,
    )


def _parse_end_date(raw: str | None, start: date | None) -> date:
    """Try to parse `fin_contrato` (legacy stored as text). Falls back to
    start + 365 days. SLAB requires end_date — never returns None."""
    if raw:
        s = raw.strip()
        # Common shapes: 'YYYY-MM-DD', 'DD/MM/YYYY', '12/2025', '2025'
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%Y", "%Y"):
            try:
                from datetime import datetime
                d = datetime.strptime(s, fmt).date()
                # 'YYYY' parsing gives Jan 1 — bump to Dec 31 of that year.
                if fmt == "%Y":
                    d = d.replace(month=12, day=31)
                # 'MM/YYYY' gives day 1 — bump to last day of that month.
                if fmt == "%m/%Y":
                    next_month = d.replace(day=28) + timedelta(days=4)
                    d = next_month - timedelta(days=next_month.day)
                return d
            except ValueError:
                continue
    # Fallback: +1 year from start_date.
    if start:
        return start + timedelta(days=365)
    # Last resort.
    return date.today() + timedelta(days=365)


def _to_decimal(v) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
