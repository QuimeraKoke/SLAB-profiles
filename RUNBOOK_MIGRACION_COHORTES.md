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

## Fase 2 — Renombrar equipos

➡️ **Hecha.** Ver "Fase 2 — Renombrar equipos a cohorte" más abajo, después de
la 3e: el renombre depende de la etiqueta derivada y del rediseño
competencia→bracket, así que está documentado en el orden en que se ejecuta, no
en el orden en que se numeró.

Las dos advertencias que tenía esta sección, resueltas:

- `unique_together = ("club", "name")` — la migración **salta** las colisiones en
  vez de usar nombres temporales. Un equipo sin renombrar sigue leyéndose bien
  por `season_label`; una migración caída bloquea el deploy entero.
- Pertenencias reales (`PlayerTeamMembership`) — las escribe la fase 1. El
  renombre **no mueve a ningún jugador**.

### Vocabulario — decidido con el club (2026-08-26)

| Tipo de equipo | Cómo se llama | Qué se lee | Texto chico |
|---|---|---|---|
| Primer equipo (atemporal) | **Equipo** | `Primer Equipo` | — |
| Los temporales, con cohorte | **Serie** | `Serie 2014` | `Sub 12` |
| Sin cohorte (Sub 20, femeninos) | el nombre guardado | `Sub 20` | — |

**La serie va primero y el bracket es la aclaración**, al revés de la primera
versión que hice: yo había puesto el bracket adelante porque es lo que la gente
dice en voz alta, y el club eligió que el nombre durable sea lo que se lee y el
escalón de la temporada el recordatorio al lado.

Implementado como **dos campos**, no un string: `season_label_parts()` devuelve
`("Serie 2014", "Sub 12")`, y `CategoryOut` los expone como `label` y
`label_hint`. Es necesario porque quien decide la tipografía es el consumidor, y
uno de ellos no puede: **un `<option>` nativo no puede estilar parte de su
texto**. Ahí se unen con raya (`Serie 2014 — Sub 12`) vía
`lib/categoryLabel.ts`; en una tabla o un chip el `label_hint` va chico y gris.

`season_label()` sigue existiendo para texto plano (PDFs, exports, emails) y
devuelve `Serie 2014 (Sub 12)` — paréntesis porque el bracket es una aclaración
sobre la temporada, no un segundo nombre.

⚠️ **Lo que sigue abierto:** el selector global sigue rotulado "Categoría", y con
este vocabulario esa palabra ya no describe lo que lista (un *Equipo* y varias
*Series*). No lo cambié porque el club no dijo qué palabra usar para el conjunto
— "Equipo" quedó reservado para el primer equipo. Falta esa sola decisión.

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

## Fase 3e — Rutas de ingesta que ignoraban a los citados ✅ HECHA en local (2026-08-26)

**Sin migración: es sólo código.** Pero tiene una consecuencia operativa en prod
que no es obvia — ver "Recuperar lo perdido" más abajo.

Encontrado contando los sitios de la fase 4. `bulk_ingest` emparejaba nombres
contra el plantel de trabajo (casa ∪ citados activos); `gps_session_ingest`,
`wellness_ingest` y `catapult_sync` **no**. Un citado aparece en el export del
plantel con el que efectivamente entrenó, así que sus filas caían en `unmatched`
y se descartaban.

Magnitud real, con 56 citaciones activas en el club:

| Equipo | Plantel de casa | Plantel de trabajo |
|---|---|---|
| SUB-18 | 16 | **35** |
| SUB-20 | 43 | 56 |
| SUB-15 | 33 | 42 |
| SUB-14 | 32 | 40 |
| SUB-16 | 26 | 30 |
| Primer Equipo | 30 | 33 |

O sea que un import de GPS para SUB-18 emparejaba contra **menos de la mitad**
del plantel que estuvo en la cancha.

### Eran dos bugs, no uno

En el GPS había que mover dos cosas juntas:

1. **El índice de nombres**, o la fila nunca resuelve → se pierde el dato.
2. **La clave de deduplicación**, que filtraba por `player__category=category`.
   Las filas de un citado cuelgan de su categoría de CASA, así que el dedup no
   las veía y las reescribía en cada corrida → se duplica el dato.

Arreglar sólo el primero convierte una pérdida silenciosa en una duplicación
silenciosa. Los dos están fijados en `exams/test_ingest_call_ups.py`, y verifiqué
que los tests **fallan** con el filtro viejo (3 de 5) — si no, no prueban nada.

### La regla vive en un solo lugar

Nuevo `core/rosters.py` con `players_in_category` / `player_ids_in_category`.
`api.scoping.players_in_category` ahora delega ahí (sus ~80 usos siguen igual).
Está en `core` y no en `api` justamente porque los importadores no podían
importarlo, y un helper que no se puede importar se reimplementa — que es
exactamente lo que había pasado.

`active_only=False` en los dos importadores de archivo: un archivo histórico
puede nombrar a alguien que ya se fue, y descartar esas filas pierde dato real.

### Recuperar lo perdido (prod)

⚠️ **El arreglo evita la pérdida futura; no reimporta lo ya descartado.** Según
la fuente:

| Fuente | ¿Se recupera? | Cómo | Alcance real |
|---|---|---|---|
| Catapult | ✅ sí | re-sincronizar: es API y deduplica | **sólo Primer Equipo** — es la única integración configurada, y son 3 citados de 56 |
| Wellness (Google Form) | ✅ sí | tarea Celery en modo `all` | todos los equipos |
| GPS entrenamiento (subida manual) | ❌ no | el club tiene que volver a subir los archivos | **el resto de los 56** |

⚠️ **El grueso no se recupera solo.** Los juveniles no usan Catapult — su GPS
entra por subida manual, y son justamente los equipos con más citados (Serie
2008: 16 de casa, 35 de trabajo). Esos archivos los tiene que volver a subir el
club, y conviene pedírselos apenas esté desplegado.

Corré los re-sync **después** de desplegar y compará el conteo de `ExamResult`
antes/después para saber cuánto se recuperó.

## Fase 2 — Renombrar equipos a cohorte ✅ HECHA en local (2026-08-26)

⚠️ **El orden es al revés del obvio, y esto es lo importante de la fase.**
Primero la etiqueta derivada, después el renombre. Renombrar primero deja a todo
el mundo leyendo "Serie 2014" cuando dice "Sub 12": dato correcto, app inusable.
Con la etiqueta ya desplegada, el renombre es **invisible** para el usuario.
(Misma lección que desacoplar antes de renombrar, de más arriba en esta
migración.)

### Paso 1 — etiqueta derivada (sin migración)

`Category.season_label(season=None)` → `"Sub 12 · Serie 2014"`. Por defecto usa
el año actual. El bracket va primero porque es lo que la gente dice; la cohorte
lo sigue porque **el bracket solo es ambiguo**: en 2026 las series 2008 y 2009
juegan las dos Sub 18, y un selector que muestre "Sub 18" dos veces no se puede
usar.

`CategoryOut` gana un campo `label` (resolver en `api/schemas.py`). `name` se
queda en el payload porque es la identidad guardada y el admin la edita, pero
**todo lo que un usuario LEE usa `label`**.

Frontend: selector global (`Navbar`), `configuraciones/jugadores`,
`configuraciones/usuarios`, `MatchForm`. El tipo `Category` documenta cuál usar.

⚠️ `season_bracket` lee la caché de `prefetch_related` cuando existe. Sin eso el
selector cuesta **una consulta por equipo**: `.filter()` sobre una relación
prefetcheada emite consulta igual, y el prefetch queda de adorno. Fijado por
`test_labelling_does_not_cost_a_query_per_team`, que compara 3 y 12 equipos en
vez de afirmar un número — un número fijo también pasaría si estuviera fijo en el
valor equivocado. Verifiqué que falla sin la lectura de caché (6 ≠ 3).

### Paso 2 — la migración

```bash
python manage.py migrate core   # 0022_rename_cohort_teams
```

Resultado en local, 7 de 16 equipos renombrados:

| Antes | Ahora | Etiqueta que se ve |
|---|---|---|
| `SUB-11` | `Serie 2014` | Sub 12 · Serie 2014 |
| `SUB-12` | `Serie 2013` | Sub 13 · Serie 2013 |
| `SUB-13` | `Serie 2012` | Sub 14 · Serie 2012 |
| `SUB-14` | `Serie 2011` | Sub 15 · Serie 2011 |
| `SUB-15` | `Serie 2010` | Sub 16 · Serie 2010 |
| `SUB-16` | `Serie 2009` | Sub 18 · Serie 2009 |
| `SUB-18` | `Serie 2008` | Sub 18 · Serie 2008 |

**Los otros 9 no se tocan, y no es una excepción: es la misma regla.** Un equipo
se llama como aquello que en él es invariante. Para un equipo de cohorte, el año
de nacimiento; para Sub 20 o el Primer Equipo, que reciclan jugadores cada
temporada, el nombre guardado *es* el invariante. Sub 20 no tiene cohorte por una
razón real: sus apariciones 2026 son 2006, 2007 y 2008 — plantel genuinamente
mezclado, no dato faltante.

Por qué es seguro ahora: **nada en el código lee dígitos del nombre.** Antes sí
—`re.search(r"(\d{1,2})")` sobre el nombre de la categoría, que lee "Serie 2014"
como **20** y habría archivado los partidos de esos chicos en Sub 20 sin un solo
error. Hoy `_category_index` lee `TeamSeason`, con
`test_a_cohort_name_does_not_poison_the_mapping` para que siga así.

La migración salta colisiones en vez de fallar (`unique_together = (club, name)`):
un equipo sin renombrar sigue leyéndose bien por `season_label`, mientras una
migración caída bloquea el deploy entero. Es idempotente y tiene `backward`, que
reconstruye un `SUB-NN` desde el bracket declarado — no exacto por construcción,
porque los nombres viejos eran una foto vieja, pero estable al revertir y volver a
aplicar.

### Lo que queda por rotular

Estas superficies muestran el nombre de la categoría desde **otros** esquemas
(embebido en el evento, en el jugador, en el PDF), así que no reciben `label`
todavía y siguen mostrando el nombre guardado:

- `/partidos/[id]` y `ProfileEvents` → `event.category.name`
- Fichas PDF: `player_triage`, `team_report`, `daily_deck`
- `/daily`, `/centro-de-mando`, `/reportes/[dept]`, `/uso`

Tras el renombre esas leen "Serie 2014" en vez de "Sub 12 · Serie 2014": quedan
**incompletas, no equivocadas**, que era el punto de renombrar. Rotularlas es
trabajo mecánico por esquema y va en una tanda aparte.

## Fase 2b — Borrar las categorías vacías ✅ HECHA en local (2026-08-26)

`SUB-8`, `SUB-9` y `SUB-10` de la U: sin jugadores (ni inactivos), sin
citaciones, sin pertenencias, sin temporadas declaradas, sin eventos. Ningún seed
las crea — vienen de la migración legacy o las hizo alguien a mano.

Por qué convenía sacarlas y no tolerarlas:

- La escalera de la ANFP **arranca en Sub 11**. Abajo no existe competencia, así
  que el feed de COMET nunca va a traer nada para ellas.
- Ocupaban 3 de 16 lugares del selector global y eran indistinguibles de un
  equipo real hasta hacer clic en una pantalla vacía.
- Bajo el modelo de cohortes un equipo real llega como `Serie YYYY` con su año de
  nacimiento. Estas no tenían `cohort_year`, así que tampoco podían alojar al
  plantel 2015 que el club todavía debe.
- ⚠️ **El job de briefings corría sobre ellas.** Cada una tenía 5
  `BriefingSnapshot` con `model="claude-opus-4-8"` e `items: []` — una llamada a
  Opus por categoría por corrida, para planteles con cero jugadores.

```bash
python manage.py migrate core   # 0023_delete_empty_categories
```

### Se eligen por VALOR, nunca por nombre

Verificado antes de escribirla: en **toda** la base hay exactamente tres
categorías que cumplen la condición, así que la regla no necesita lista de
nombres ni señala la costumbre de nomenclatura de un club.

### Falla-segura por construcción

El chequeo recorre `Category._meta.related_objects` y trata como bloqueante
**cualquier** relación que no reconozca explícitamente. Si alguien agrega un FK a
`Category` el año que viene y se olvida de este archivo, una categoría con filas
ahí deja de ser borrable en vez de irse en cascada. Una lista fija de cosas a
revisar se desactualiza justo en la dirección que pierde datos.

Sólo tres relaciones se aceptan como colateral: los dos M2M
(`StaffMembership.categories`, `ExamTemplate.applicable_categories`) y
`BriefingSnapshot`, que es caché de LLM y se regenera.

⚠️ **Prod puede no verse como local.** Si allá alguna de esas categorías tiene
jugadores, la migración **la salta** y sigue: es un guard, no un `DELETE`.

### Respaldo

`backend/core/fixtures/deleted_categories_2026-08-26.json` — nombre, configs,
departamentos, plantillas y snapshots de las tres. `backward` es un `pass` a
propósito: recrearlas inventaría UUIDs nuevos, que no es lo mismo que deshacer.

## Fase 2c — Disolver SUB-17 ✅ HECHA en local (2026-08-27)

Apareció mirando por qué el selector mostraba **tres cosas que decían "Sub 18"**.
Dos eran correctas y una era un cajón.

**Las correctas:** Serie 2008 cumple 18 en 2026, y Serie 2009 cumple 17 — y la
ANFP **no corre Sub 17 ni Sub 19**, así que los del 2009 suben a Sub 18 y
comparten competencia. Se repite todos los años en Sub 18 y Sub 20, y es
exactamente por esto que la serie tiene que ir adelante en la etiqueta: con el
bracket primero esas dos entradas serían "Sub 18" y "Sub 18".

**El cajón:** `SUB-17` no era un equipo. Tenía 2 jugadores y **6 partidos del
Sudamericano Sub-17 2025 de la selección chilena**. Se veía como un "Sub 18"
pelado porque al mezclar un 2008 con un 2009 el backfill no pudo darle cohorte
(50/50, bajo el umbral de 70 %).

La pista de cómo debía estar modelado estaba en los mismos datos: un **tercer**
jugador de esos 6 partidos, Benjamín Díaz, conservó su equipo real (SUB-20) y
figura sólo como `EventParticipant`. Eso es lo correcto, y es lo que a los otros
dos no se les hizo.

```bash
python manage.py migrate core   # 0024 y 0025
```

| | |
|---|---|
| Renato Nuñez (2008) | → Serie 2008 |
| Andher Gonzalez (2009) | → Serie 2009 |
| Los 6 partidos de selección | desprendidos (`category=NULL`) |
| Pertenencias | re-apuntadas a la serie real |
| `TeamSeason` 2026 derivada | borrada |
| `SUB-17` | borrado por la regla de 0023 |

Nadie pierde nada: los 6 partidos siguen en el perfil de los tres jugadores
porque el calendario resuelve **por participación, nunca por `Event.category`**.
Verificado después de migrar: Nuñez conserva 43 exámenes y Gonzalez 38, y los 6
partidos siguen listando a los tres.

### Por qué va por IDs y no por regla

La generalización obvia —"mové cada jugador a la Serie de su año de
nacimiento"— era peligrosa, y la base lo dice:

| Categoría sin cohorte | Jugadores | Nacimientos |
|---|---|---|
| SUB-20 | 43 | 2004–2009 ← equipo real, se habría desarmado en 6 series |
| PEF - Femenino | 20 | 1985–1997 |
| SUB-19 F - Femenino | 16 | 2005–2008 |
| **SUB-16 F - Femenino** | **1** | **2009** ← se habría ido a Serie 2009, masculina |

Así que es una corrección puntual registrada como dato, que es para lo que sirve
una migración. Las guardas son lo que la hace segura en vez de confiar en los
ids: **cada movimiento vuelve a verificar el hecho que lo justifica** (año de
nacimiento, club, y sexo contra el plantel destino) y se omite si ya no se
cumple. Prod es la fuente de verdad y puede no verse como local.

⚠️ 0025 existe porque 0024 **se negó** a borrar el cajón: quedaban 2
pertenencias y 1 temporada apuntando ahí. Esa negativa fue la guarda funcionando.
Ninguno de los dos era dato real —las pertenencias las había escrito el backfill
con `since` = fecha del primer partido del Sudamericano, y la temporada era
`derived=True`— así que 0025 las corrige y vuelve a pasar el cajón por la misma
regla de 0023. **Una sola definición de "no tiene nada", aplicada desde tres
migraciones.**

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
| ~~Bio-banding (maturity offset)~~ | ✅ **HECHO** (2026-08-24). Mirwald + velocidad de crecimiento en `api/maturation.py`, módulo `/crecimiento`: 214 jugadores con maduración calculada en 8 cohortes, filtros de situación y sugerencia de equipo. | PRD §9.1 / §9.3-A |
| ~~20 filas de antropometría con columnas corridas~~ | ✅ **RESUELTO** (2026-08-24): eran corruptas en origen (masa ósea negativa en la base legacy del club), irreparables, borradas con respaldo JSON. No hay xlsx del que reimportar. Si el club consigue el export ISAK original, se pueden recuperar. | PRD §9.2 |
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

## Estado actual (2026-08-27)

| | Local | Prod |
|---|---|---|
| Datos COMET 2026 | ✅ copia de prod (2026-08-22) | ✅ 155 eventos / 2.588 fichas |
| `core.0019` (bracket/cohorte/pertenencias) | ✅ | ✅ aplicada |
| `core.0020` + `0021` (`is_senior`) | ✅ | ❌ **pendiente** |
| `core.0022` (renombre a cohorte) | ✅ | ❌ **pendiente** |
| `core.0023` (borrar categorías vacías) | ✅ | ❌ **pendiente** |
| `core.0024` + `0025` (disolver SUB-17) | ✅ | ❌ **pendiente** |
| `events.0007` (`Event.bracket`) | ✅ | ❌ **pendiente** |
| `exams.0031` (competencia → bracket) | ✅ | ❌ **pendiente** |
| Backfill fases 1 + 3a | ✅ verificado | ⚠️ fase 1 sí, 3a no |
| Re-apuntado de partidos (3c) | ✅ 183 eventos | ❌ pendiente |
| Fixtures futuros | ✅ 101 eventos | ❌ pendiente |
| Código en git | **38 commits locales** | `639e1d4` (no conoce estos modelos) |
| Tests | **581 OK** | — |

⚠️ **Prod tiene la base por delante del código, y local por delante de prod.**
Nada en `639e1d4` lee esas tablas, así que lo ya aplicado en prod es inerte.
Decisión del 2026-08-22: se acepta como adelanto y se valida en local.

### Orden de despliegue

Las migraciones son aditivas y van primero sin riesgo para el código viejo. La
única excepción es `core.0022`, el renombre: **no la corras antes de que el
código nuevo esté desplegado**, porque el `639e1d4` que hay hoy en prod todavía
lee dígitos del nombre de la categoría y leería "Serie 2014" como Sub 20.

```bash
# ── 1. migraciones seguras con el código viejo ────────────────────────────
manage.py migrate core     # 0020, 0021  (0019 ya está)
manage.py migrate events   # 0007
manage.py migrate exams    # 0031

# ── 2. backfill: brackets, TeamSeason, pertenencias ──────────────────────
manage.py backfill_cohorts --club "Universidad de Chile" --commit

# ── 3. re-apuntar los partidos ya sincronizados (fase 3c) ────────────────
#     DESPUÉS del backfill: sin TeamSeason cae al parseo del nombre y
#     reproduce el error que viene a arreglar. Corré primero en seco.
manage.py repoint_comet_events --club "Universidad de Chile"
manage.py repoint_comet_events --club "Universidad de Chile" --commit

# ── 4. push → Railway despliega backend, frontend, Celery y beat ─────────

# ── 5. SÓLO con el código nuevo arriba: renombre y limpieza ──────────────
#     0022 renombra; 0023 borra las vacías; 0024+0025 disuelven SUB-17.
#     Las tres últimas son guards: si prod tiene datos donde local no, se
#     saltan solas y lo informan.
manage.py migrate core     # 0022, 0023, 0024, 0025

# ── 6. recuperar lo que la ingesta vieja descartó (fase 3e) ──────────────
#     Contá ExamResult antes y después para saber cuánto se recuperó.
#     Catapult va POR CATEGORÍA (no acepta --club) y sólo hay UNA integración
#     configurada: Primer Equipo. Los juveniles no usan Catapult, su GPS entra
#     por subida manual — así que ahí no hay nada que recuperar por API.
#     Alcance real: 3 citados de los 56.
manage.py sync_catapult --category "Primer Equipo" --commit
manage.py sync_comet --club "Universidad de Chile" --days 30 --commit

#     Wellness no tiene comando: es una tarea Celery. Los modos son
#     today | reconcile | all — para recuperar hace falta el completo:
manage.py shell -c "from exams.tasks import sync_wellness_responses; \
print(sync_wellness_responses(mode='all'))"
```

### Verificaciones después de desplegar

| Qué | Cómo | Esperado |
|---|---|---|
| Partidos bien archivados | `repoint_comet_events` en seco | "sin cambios" |
| Competencias resueltas | admin → Competencias COMET | bracket en todas; sólo "Sub 11" sin equipo |
| Etiquetas | selector global | "Sub 12 · Serie 2014", no "SUB-11" |
| Senior intacto | `/partidos` con Primer Equipo | los 43 eventos senior siguen ahí |

### Lo que sigue esperando al club

- **¿Las series 2008 y 2009 son un plantel o dos?** Son los 23 partidos Sub 18
  sin resolver. Se arregla con una fila en `category_override`.
- Plantel 2015 (engancharía los 29 partidos desprendidos de "Sub 11").
- Volver a subir los archivos de GPS de entrenamiento que la ingesta vieja
  descartó — esos no se recuperan solos.
