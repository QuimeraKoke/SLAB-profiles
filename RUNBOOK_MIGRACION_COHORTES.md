# Runbook — migración a equipo/temporada (cohortes)

Pasos ejecutables para `PRD_EQUIPO_TEMPORADA.md`. Cada fase indica qué escribe,
cómo verificarla y **cómo revertirla**.

> **Regla de este proyecto:** validar en local con datos reales antes de tocar
> prod. Ver §0 — local está por detrás de prod y hay que igualarlo primero.

---

## 0. Prerrequisito: local tiene que tener los datos de 2026

Local fue restaurado desde prod el 2026-08-18 y **no tiene** la carga COMET
juvenil hecha después (155 eventos, 2.588 fichas, 2026). Sin eso, el backfill
deriva las temporadas 2026 "de la edad" en lugar de leerlas de los partidos, y
produce filas equivocadas — verificado: en local `SUB-20 2026` resolvía a
`Primera` porque los únicos eventos de 2026 en local eran de Primer Equipo.

Dos caminos:

**A. Copiar prod a local** (recomendado, ~10 min)

```bash
# 1. Dump de prod
PGPASSWORD=<prod> pg_dump -h tramway.proxy.rlwy.net -p 35704 -U postgres \
  -d railway -Fc -f /tmp/prod_$(date +%Y%m%dT%H%M%S).dump

# 2. Restaurar en local (⚠️ ver reference_host_shell_gotchas antes de tocar
#    cualquier contenedor de Postgres de este proyecto)
docker compose up -d postgres
docker compose exec -T postgres psql -U slab -d postgres \
  -c 'DROP DATABASE IF EXISTS slab; CREATE DATABASE slab OWNER slab;'
PGPASSWORD=slab pg_restore -h localhost -U slab -d slab --no-owner /tmp/prod_*.dump

# 3. Migraciones locales
docker compose run --rm --no-deps -T backend python manage.py migrate
```

**B. Resincronizar COMET contra local** (~2 h, vuelve a pegarle a la API)

```bash
docker compose run --rm --no-deps -T -e POSTGRES_HOST=postgres backend \
  python manage.py sync_comet --club "Universidad de Chile" --days 210 --commit
```

Preferir A: es más rápido y garantiza paridad exacta con prod.

### Verificación de §0

```sql
-- Debe dar 155 eventos creados por COMET y ~2.588 fichas.
SELECT count(*) FROM events_event
 WHERE event_type='match' AND metadata ? 'comet_match_id';
SELECT count(*) FROM exams_examresult r
  JOIN exams_examtemplate t ON t.id=r.template_id
 WHERE t.slug='ficha_partido';
```

---

## Fase 0 — Modelos (aditiva)

`Bracket`, `TeamSeason`, `PlayerTeamMembership`, `Category.cohort_year`.

```bash
docker compose run --rm --no-deps -T -e POSTGRES_HOST=postgres backend \
  python manage.py migrate core
```

- **Escribe:** 3 tablas nuevas + 1 columna nullable.
- **Riesgo:** nulo. Ningún código la consume; el código viejo no ve la columna.
- **Verificar:** `\dt core_bracket core_teamseason core_playerteammembership`
- **Revertir:** `python manage.py migrate core 0018`

## Fase 1 — Backfill (aditiva, no toca `Player.category`)

```bash
# Dry-run primero, SIEMPRE.
python manage.py backfill_cohorts --club "Universidad de Chile"
python manage.py backfill_cohorts --club "Universidad de Chile" --commit
```

- **Escribe:** filas de `Bracket` (9), `TeamSeason`, `PlayerTeamMembership`, y
  `Category.cohort_year`.
- **NO escribe:** `Player.category`. Ningún jugador cambia de equipo.
- **Idempotente:** re-correr no duplica. Respeta `TeamSeason.derived=False`
  (una corrección humana nunca se pisa) y salta pertenencias abiertas.

### Umbrales que aplica, y por qué

| Umbral | Valor | Motivo |
|---|---|---|
| `MIN_COHORT_SHARE` | 70 % | El modelo de cohorte **encaja abajo y degrada arriba**: SUB-11…SUB-14 son 100 % un solo año de nacimiento, SUB-20 es 33 % (43 jugadores de 2004 a 2008) y SUB-17 es 50 %. Sub 20 no es un cohorte, es un plantel con forma de bracket; inventarle uno afirmaría algo falso. Debajo del umbral queda `NULL`, que el modelo ya interpreta como "no es grupo de edad". |
| `MIN_APPEARANCES` | 3 | Una aparición de invitado no puede decidir la temporada. |
| `MIN_SEASON_SHARE` | 60 % | Ídem por proporción: `SUB-17 2025` resolvía a Sub 20 con 4/9 (44 %) y queda sin decidir, para que lo defina el club. |

### Resultado esperado (prod, 2026-08-22)

Cada equipo se mueve **exactamente un escalón** entre temporadas, y SUB-16 salta
a Sub 18 porque **Sub 17 no existe en la ANFP**:

| Equipo | 2025 | 2026 |
|---|---|---|
| SUB-11 | Sub 11 (100 %) | Sub 12 (100 %) |
| SUB-12 | Sub 12 (100 %) | Sub 13 (95 %) |
| SUB-13 | Sub 13 (100 %) | Sub 14 (85 %) |
| SUB-14 | Sub 14 (98 %) | Sub 15 (94 %) |
| SUB-15 | Sub 15 (94 %) | Sub 16 (82 %) |
| SUB-16 | Sub 16 (98 %) | **Sub 18** (84 %) |
| SUB-18 | Sub 18 (92 %) | Sub 18 (62 %) |
| SUB-20 | Sub 20 (90 %) | Sub 20 (70 %) |
| Primer Equipo | Primera (86 %) | Primera (89 %) |

Sin cohorte (correcto): SUB-17, SUB-20, y los vacíos SUB-8/9/10.
Sin decidir: `SUB-17 2025`.

### Verificación de fase 1 — criterio §7.1 del PRD

```sql
-- Coincidencia player.team + TeamSeason.bracket vs la categoría del evento,
-- por temporada. Objetivo: >= 95 % en AMBAS.
-- Antes de la migración: 93,6 % en 2025 y 16,8 % en 2026.
WITH x AS (
  SELECT extract(year FROM e.starts_at)::int AS season,
         ts.bracket_id AS esperado,
         b2.id         AS real_id
  FROM events_eventparticipant ep
  JOIN events_event e   ON e.id = ep.event_id
  JOIN core_player p    ON p.id = ep.player_id
  JOIN core_category ce ON ce.id = e.category_id
  LEFT JOIN core_teamseason ts
         ON ts.team_id = p.category_id
        AND ts.season  = extract(year FROM e.starts_at)::int
  LEFT JOIN core_bracket b2
         ON b2.name = replace(ce.name, 'SUB-', 'Sub ')
         OR (ce.name = 'Primer Equipo' AND b2.code = 'primera')
  WHERE e.event_type = 'match' AND ce.name NOT LIKE '%F -%'
)
SELECT season, count(*) AS total,
       count(*) FILTER (WHERE esperado = real_id) AS coinciden,
       round(100.0 * count(*) FILTER (WHERE esperado = real_id) / count(*), 1) AS pct
FROM x GROUP BY season ORDER BY season;
```

Lo que **no** coincida debe ser préstamo real (jugar por encima del bracket del
equipo). Contrastar contra el 26 % medido; si sube a 85–100 %, algo volvió a
comparar etiquetas en lugar de cohortes.

### Revertir fase 1

```sql
BEGIN;
DELETE FROM core_playerteammembership WHERE reason LIKE 'carga inicial%';
DELETE FROM core_teamseason WHERE derived = true;
UPDATE core_category SET cohort_year = NULL;
-- Los brackets se pueden dejar: son la escalera de la federación, no datos del club.
COMMIT;
```

---

## Fase 2 — Renombrar equipos + pertenencias reales

Pendiente. `SUB-11` → `Serie 2014`, etc. Sólo cambia `Category.name`; **ningún
jugador se mueve**. Reversible con el mapeo inverso.

⚠️ `Category` tiene `unique_together = ("club", "name")`: renombrar en cascada
puede chocar transitoriamente (dos equipos queriendo llamarse igual a mitad de
camino). Hacerlo en una transacción con nombres temporales.

⚠️ Toca la regla de IA nº 3 de `AGENTS.md` ("una etiqueta = un significado"):
`Categoría` deja de ser un término único y hay que nombrar **Equipo** y
**Categoría de competencia** distinto en toda la UI.

## Fase 3 — `Event.bracket` y calendario

Pendiente y es el cambio más profundo. Un partido de Sub 18 lo juegan **dos
equipos a la vez** (cohortes 2009 y 2008), así que `Event.category` como FK único
no los representa. Requiere decisión de producto: ¿el partido aparece en el
calendario de los dos equipos o sólo en el del cohorte principal?

## Fase 4 — Auditar los filtros por categoría

Pendiente. 146 sitios `category=`, 67 `category__`, 51 `player__category`. Cada
uno hay que clasificarlo como **grupo de trabajo** o **plantel que jugó**: con el
préstamo al 26 %, un filtro plano deja fuera a un cuarto del plantel real **sin
avisar**. Es el trabajo más tedioso y el que más errores silenciosos deja.

---

## Estado actual (2026-08-22)

| | Local | Prod |
|---|---|---|
| Datos COMET 2026 | ❌ falta (ver §0) | ✅ 155 eventos / 2.588 fichas |
| Migración `core.0019` | ✅ aplicada | ✅ aplicada |
| Backfill fase 1 | ❌ no corrido | ⚠️ **corrido** (9/19/310/7) |
| Código en git | sin comitear | `639e1d4` (no conoce estos modelos) |

⚠️ **Prod tiene la base por delante del código.** Es inerte —nada en
`639e1d4` lee esas tablas— pero conviene igualar antes de desplegar: o se revierte
la fase 1 en prod (§ "Revertir fase 1") y se rehace después de validar en local,
o se acepta como adelanto y se valida sobre eso.
