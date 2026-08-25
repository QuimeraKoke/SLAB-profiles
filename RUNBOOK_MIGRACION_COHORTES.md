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

## Fase 3a — `Event.bracket` ✅ HECHA

```bash
python manage.py migrate events          # 0007_event_bracket
python manage.py backfill_cohorts --club "Universidad de Chile" --commit
```

538 partidos con bracket: 155 por nombre oficial de competencia (COMET) y 377 por
la etiqueta del evento, que es segura en las dos temporadas porque **el desfase
está entre la etiqueta DEL JUGADOR y la temporada, no la del evento**. Los 37 que
quedan sin bracket son todos femeninos, correcto: el feed no trae esas
competencias.

⚠️ `SUB-17` tiene 6 partidos y NO existe competencia Sub 17, así que la búsqueda
por edad exacta los dejaba huérfanos. Usan `bracket_for_age` y caen en Sub 18.
Debajo de la escalera es al revés: un partido Sub 9 es torneo local y promoverlo
a Sub 11 inventaría una competencia, así que queda sin resolver a propósito.

También se sincronizan los **fixtures futuros** (`sync_future_fixtures`): 100
programados, 90 creados y **10 adoptados** — la ventana de ±16 h reconoce los
eventos que ya había creado `fixtures_sync` en vez de duplicarlos.

## Fase 3b — Semántica del calendario ⏸ espera decisión del club

**El alcance es mucho menor de lo que decía la primera versión de este runbook.**
Medido: de 17 combinaciones bracket-temporada, **sólo una tiene más de un equipo
compitiendo** — Sub 18 2026, con SUB-16, SUB-17 y SUB-18. Son **22 partidos** que
pasarían de 1 a 3 calendarios (a 2 si SUB-17 se desarma).

Los otros ~44 partidos que *parecían* compartidos son préstamos: un equipo dueño
y otros aportando jugadores sueltos. Eso **ya está resuelto** y no toca el
calendario del equipo, porque un jugador ve ese partido por ser
`EventParticipant`, no porque su equipo compita ahí.

Con eso **no hace falta la noción de "equipo principal"**: el partido aparece en
el calendario de todo equipo cuyo `TeamSeason.bracket` coincida, que es la
verdad. Ya implementado en `api/fixtures.py`; falta sólo confirmar la regla con
el club.

Se repite cada temporada en Sub 18 y Sub 20 (los brackets de los huecos), así que
es permanente pero de volumen chico.

## Fase 3c — Re-apuntar los partidos COMET ✅ HECHA en local (2026-08-24)

**El hallazgo más grave de toda la migración, y no estaba en el PRD.** De los
**215 partidos juveniles COMET de 2026, cero** estaban archivados en el equipo
correcto. Todos corridos exactamente un escalón hacia abajo.

Causa: `_resolve_category` leía el token "Sub NN" del nombre de la competencia y
lo emparejaba con la categoría SLAB de los mismos dígitos. Los nombres de los
equipos son la foto congelada de 2025, así que el emparejamiento por nombre
archiva mal por definición. El calendario de `SUB-12` mostraba los partidos que
jugaron los chicos de `SUB-11`.

Cómo se comprobó, sin circularidad — qué años de nacimiento aparecen realmente
en cada competencia según las nóminas de COMET:

| Competencia 2026 | Nacidos que juegan | SLAB lo llamaba |
|---|---|---|
| Sub 12 | **2014** (239 de 239) | `SUB-11` |
| Sub 13 | **2013** (191 de 191) | `SUB-12` |
| Sub 14 | 2012 dominante | `SUB-13` |
| Sub 15 | 2011 | `SUB-14` |
| Sub 16 | 2010 | `SUB-15` |
| Sub 18 | 2009 + 2008 | `SUB-16` y `SUB-18` |

⚠️ **El arreglo de `_category_index` no sana lo ya sincronizado.**
`_competition_link` sólo re-resuelve un link cuya categoría sigue en NULL, así
que un `CometCompetitionLink` archivado por el camino viejo se queda con su
categoría equivocada para siempre y cada partido nuevo la hereda. De ahí que
haga falta un comando y no baste con re-sincronizar.

```bash
python manage.py repoint_comet_events --club "Universidad de Chile"            # dry run
python manage.py repoint_comet_events --club "Universidad de Chile" --commit
```

Resultado en local: **183 eventos re-apuntados, 16 competencias re-vinculadas**
(154 movidos de equipo + 29 desprendidos), 43 senior intactos, 62 ya correctos.

Lo que **no** toca, a propósito:

- **Primer Equipo.** Las competencias senior (Primera, Copa Chile, CONMEBOL) no
  llevan token de edad y se resuelven por `is_senior`, que nunca tuvo el
  corrimiento. El equipo senior es atemporal: no tiene cohorte y nada de esta
  aritmética le aplica.
- **Links que resolvió una persona** (`auto_resolved=False`) o que están
  aparcados (`ignored=True`).
- **`Event.bracket`.** Ya estaba bien: sale del nombre oficial de la competencia,
  no del nombre del equipo.

**Huérfanos.** Los 29 partidos de "Sub 11" 2026 se **desprenden**
(`category=None`), no se borran. Esa competencia es de la serie 2015, plantel que
SLAB no tiene cargado — y la prueba es que 17 ya se jugaron sin una sola nómina,
mientras todos los demás escalones sí las tienen. Desprenderlos es lo que evita
que inflen el calendario de `SUB-11` con partidos que sus chicos nunca jugaron.
Si algún día entra el plantel 2015, se re-corre el comando y se enganchan.

La temporada se lee **por evento**, no por link: el mapeo cohorte→bracket es
específico del año, así que un partido de 2025 y uno de 2026 del mismo equipo
resuelven por índices distintos.

### Verificación de fase 3c

```bash
# antes: 0 coherentes / 122 cohorte distinta / 93 sin nómina  (de 215)
# ahora: 101 coherentes / 23 cohorte distinta / 62 sin nómina (de 186)
```

Los 62 sin nómina son todos de fecha futura: COMET no publicó la alineación
todavía. Los 23 que quedan son **la ambigüedad 2008/2009 en Sub 18**, y no es un
bug: las dos cohortes compiten en el mismo bracket y `_category_index` se queda
con la más vieja. Resolverlo requiere que el club diga **si la serie 2008 y la
2009 son un plantel o dos** — ver fase 3b.

⚠️ **Orden en prod:** este comando depende de que `TeamSeason` ya esté poblada,
así que va **después** de `backfill_cohorts --commit` (fase 1), nunca antes. Sin
`TeamSeason` el índice cae al parseo del nombre y el comando reproduce el mismo
error que viene a arreglar.

## Fase 3d — Competencia → bracket ✅ HECHA en local (2026-08-25)

El arreglo de fondo de la fase 3c. Esa reparó 183 filas; esta hace que la falla
**no pueda volver a ocurrir**.

`CometCompetitionLink.category` guardaba *"qué equipo juega esta competencia"*,
que no es un hecho de la competencia sino un **cruce**: `bracket ⋈
TeamSeason(temporada)`. Su lado izquierdo no cambia nunca; el derecho cambia cada
enero. Guardar el resultado del cruce es lo que hizo que corregir
`_category_index` no sanara ni una fila.

Lo que se guarda ahora es el hecho:

| Columna | Antes | Ahora |
|---|---|---|
| `bracket` | no existía | **el hecho** de la federación, resuelto del nombre |
| `category` → `category_override` | cache automática **y** override humano, distinguidos por `auto_resolved` | **sólo** override humano |
| `auto_resolved` | marcaba la cache | **eliminada**: el override no-nulo ya es la marca |

El equipo lo calcula `resolve_link_category(link, club, season=…)` al leer. Sin
cache no hay nada que pueda quedar viejo — es la clase de bug entera, no una
instancia.

```bash
python manage.py migrate exams   # 0031_comet_competition_bracket
```

La migración de datos deriva el bracket del nombre de cada competencia y
**descarta** las categorías que había escrito la máquina, conservando sólo las que
puso una persona. Tiene `backward`, que re-deriva la cache para que el código
viejo tenga qué leer.

### Verificación de fase 3d

Los 26 links del club quedaron con bracket; 23 resuelven a equipo y 3 no — los
"Sub 11", correcto, porque no hay plantel 2015. Las senior (Primera División,
GRUPO D, Primera Fase) resuelven a Primer Equipo por el flag `is_senior`.

Y lo importante: `repoint_comet_events` en seco dice **"sin cambios: todo ya está
archivado donde corresponde"** (259 ya correctos, 29 sueltos). La resolución
calculada coincide exactamente con lo que la fase 3c había dejado, o sea que el
rediseño no cambia comportamiento sobre datos reales.

### Dos nombres hardcodeados que se fueron

- `Bracket.objects.filter(code="primera")` → `Bracket.senior()`, que busca por
  `age IS NULL`. `Bracket.is_senior` es **propiedad derivada, no columna**: `age
  is None` ya es la señal y un flag guardado podría contradecirla.
- El bucle de fixtures re-derivaba el bracket del nombre — segunda copia de la
  regla de los huecos de la escalera. Ahora lee `link.bracket`.

### Lo que sigue necesitando una persona

El override existe para los brackets que tienen más de un equipo del club. Hoy
eso es **Sub 18 2026**, con las series 2008 y 2009. El cruce se queda con la más
vieja; si el club dice que son dos planteles distintos, se fija en el admin
(columna `category_override`) y listo — una fila, no una regla en el código.

El admin muestra una columna `Equipo (calculado)` de sólo lectura al lado, para
que se vea qué produce el cruce **antes** de decidir fijarlo.

## Fase 4 — Auditar los filtros por categoría

Pendiente. 146 sitios `category=`, 67 `category__`, 51 `player__category`. Cada
uno hay que clasificarlo como **grupo de trabajo** o **plantel que jugó**: con el
préstamo al 26 %, un filtro plano deja fuera a un cuarto del plantel real **sin
avisar**. Es el trabajo más tedioso y el que más errores silenciosos deja.

---

## Pendientes que esperan datos, no código

| Pendiente | Qué falta | Dónde está descrito |
|---|---|---|
| Detección de talento con GPS | GPS juvenil (hoy: 0 filas en toda la cantera). No requiere Catapult — 5.830 de 6.331 filas entraron por carga manual, y `/gps-entrenamiento` ya la soporta. Umbral útil: ≥8 jugadores por sesión y ≥3 apariciones por jugador. | PRD §8 |
| **Bio-banding (maturity offset)** | **Nada — los datos ya están.** Talla, talla sentado y peso al 100 % en 1.185 mediciones juveniles seriadas, que es el insumo exacto de Mirwald. Falta código, y arreglar §9.2 primero. | PRD §9.1 / §9.3-A |
| ⚠️ **20 filas de antropometría con columnas corridas** | Re-importar dos lotes desde el xlsx: SUB-11 del 2025-04-07 y SUB-14 del 2026-03-30. Edad→peso, peso→talla, talla→talla_sentado. Produce +62 cm de crecimiento en 4 meses y ya tuerce los gráficos de esos chicos. | PRD §9.2 |
| Proyección de talla adulta (%PAH) | **Talla de los padres** — no existe en ningún template. Se mide una vez por jugador y no cambia; mejor un campo en la ficha que un examen. | PRD §9.3-B |
| Plantel del cohorte 2015 | Los Sub 11 de 2026 son nacidos en 2015 y no existe ninguno en SLAB, así que sus 6 partidos tienen 0 fichas. | PRD §5 |
| **71 personas COMET sin vincular** | **No se resuelve vinculando: se resuelve cargando planteles.** Con el piso de matcheo real, 70 de las 71 no tienen candidato — 69 llevan dorsal juvenil y el club no tiene ningún nacido en 2015 (el cohorte de Sub 11 2026). La única decidible es GUZMAN DAVID, ambigua entre dos homónimos con RUT distinto. Ver abajo qué pasa cuando los planteles lleguen. | — |
| Calendario compartido | Decisión de producto sobre Sub 18 2026 (22 fixtures, 3 equipos). Consultado al club; puede desarmarse SUB-17. | PRD §3.1 |

## Cuando lleguen los planteles juveniles que faltan

Lo que pasa **solo**, sin tocar nada: la resolución de jugadores se reintenta en
cada corrida mientras el vínculo siga vacío (`comet_sync.py`, el guard
`link.player_id is None and match_method != MANUAL`). Así que el beat de las :45
engancha a los jugadores nuevos y empieza a escribir sus fichas. Las filas de la
cola se vacían sin intervención en el admin.

Lo que **sí** hay que correr una vez, porque el beat usa ventana de 30 días y
sólo cubriría los partidos recientes:

```bash
python manage.py sync_comet --club "Universidad de Chile" --days 210 --commit
```

Verificación:

```sql
-- Debe bajar de 71 hacia 0 (menos los que realmente no son del club).
SELECT count(*) FROM exams_cometplayerlink WHERE player_id IS NULL;
-- Y las fichas de las categorías nuevas deben aparecer.
SELECT c.name, count(*) FROM exams_examresult r
  JOIN exams_examtemplate t ON t.id=r.template_id AND t.slug='ficha_partido'
  JOIN core_player p ON p.id=r.player_id
  JOIN core_category c ON c.id=p.category_id
 GROUP BY 1 ORDER BY 2 DESC;
```

En el admin, filtrar «candidatos en el plantel» → *candidato único* para revisar
lo que el matcheo automático no cerró. Hoy eso da 0 filas, que es la respuesta
correcta: no hay nada que vincular hasta que existan los jugadores.

## Estado actual (2026-08-22)

| | Local | Prod |
|---|---|---|
| Datos COMET 2026 | ✅ copia de prod (2026-08-22) | ✅ 155 eventos / 2.588 fichas |
| Migración `core.0019` | ✅ aplicada | ✅ aplicada |
| Migración `events.0007` (bracket) | ✅ aplicada | ❌ **pendiente** |
| Backfill fases 1 + 3a | ✅ corrido y verificado | ⚠️ fase 1 sí, 3a no |
| Fixtures futuros | ✅ 101 eventos | ❌ pendiente |
| Código en git | 8 commits locales | `639e1d4` (no conoce estos modelos) |

⚠️ **Prod tiene la base por delante del código, y local por delante de prod.**
Nada en `639e1d4` lee esas tablas, así que todo lo aplicado en prod es inerte.
Decisión tomada el 2026-08-22: se acepta como adelanto y se valida en local.

Orden al desplegar (las migraciones son aditivas, así que van primero sin riesgo
para el código viejo):

```bash
# 1. migraciones
manage.py migrate core     # 0019 — ya aplicada en prod
manage.py migrate events   # 0007 — PENDIENTE en prod
# 2. backfill (incluye brackets de evento y fixtures futuros)
manage.py backfill_cohorts --club "Universidad de Chile" --commit
manage.py sync_comet --club "Universidad de Chile" --days 30 --commit
# 3. push → Railway despliega backend, frontend, Celery y beat
```
