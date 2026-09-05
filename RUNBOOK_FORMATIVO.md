# Runbook — importar los datos oficiales de Formativo (U. de Chile)

Pasos ejecutables para `PLAN_FORMATIVO.md`. Cada fase indica el comando exacto,
qué escribe, cómo verificarla y **cómo revertirla**.

> **Regla de este proyecto:** validar en local con datos reales antes de tocar
> prod. Todo lo de acá está aplicado en **local** al 2026-09-02; **nada** se
> subió a prod todavía.

## Las fuentes

El club **no trabaja sobre archivos**: mantiene dos Google Sheets y reparte
exports `.xlsx` de ellas. Los importadores leen las dos cosas — se le pasa una
ruta a un `.xlsx` o el **id del documento vivo**, y el resto es idéntico
(`exams/formativo_sources.py`).

| Documento | Id |
|---|---|
| GPS | `1WHlhb-K1Pbk1-ttkkCzdIMT69RCfYzXhDyzFXMI4_vo` |
| Evaluaciones físicas | `1F_1hUR3DsO70ziLiyja-QZW-j2727W5CsS53XWUY6BU` |

Acceso: la **misma** cuenta de servicio que el formulario de wellness
(`slab-uchile-gdrive@slab-platform-501001.iam.gserviceaccount.com`), ya
compartida en los dos documentos. No hace falta credencial nueva.

⚠️ **Tres cosas cambian entre el export y el documento vivo**, y las tres
serían silenciosas:

1. **Los títulos de hoja se truncan a 31 caracteres en un export.** El vivo
   `FORMATO CONDICIONAL 15-16 y 18-20` llega como
   `FORMATO CONDICIONAL 15-16 y 18-`. `match_sheet` resuelve los dos; comparar
   por string exacto no encontraría ninguna hoja y sembraría cero bandas.
2. **Los números renderizados son lossy.** La misma celda de `DT (m)` se lee
   `4.159` como texto y `4158.9` en crudo, porque el punto es separador de
   MILES. Leer el texto divide cada distancia por mil sin que nada avise, así
   que el lado de Sheets siempre pide `UNFORMATTED_VALUE`.
3. **Las fechas renderizadas son ambiguas** (`8/01/2025`), que es la moneda al
   aire día/mes que ya nos costó dos fechas de nacimiento. Sin formato son
   números de serie, que son exactos — y se convierten **sólo en las columnas
   de fecha**, nunca a ciegas: una `DURACIÓN (m)` de 37 también es un serial
   válido y se volvería 1900-02-05.

### Sincronización automática

Dos ticks diarios en Celery Beat (`config/celery.py`), y no cada hora por tres
razones: cada corrida lee los dos documentos completos (~20.000 filas, un par
de minutos), el club los edita a ráfagas y no de forma continua, y los dos
ingests son idempotentes por `origen_id`, así que un tick perdido no cuesta
nada.

| Tarea | Cuándo | Por qué |
|---|---|---|
| `formativo-sheets-morning` | 06:40 local | antes de la reunión de la mañana |
| `formativo-sheets-evening` | 20:40 local | levanta el entrenamiento del día |

Se lee la hoja **completa** en cada corrida, no una ventana por fecha: el club
corrige filas viejas —completa una fecha que faltaba, arregla un dato— y una
ventana se perdería esas correcciones.

Variables de entorno (blanquear un id ⇒ esa mitad del sync no hace nada):

```
FORMATIVO_GPS_SHEET_ID=1WHlhb-K1Pbk1-ttkkCzdIMT69RCfYzXhDyzFXMI4_vo
FORMATIVO_EVAL_SHEET_ID=1F_1hUR3DsO70ziLiyja-QZW-j2727W5CsS53XWUY6BU
FORMATIVO_CLUB=Universidad de Chile
# ya configuradas para wellness:
GOOGLE_SHEETS_CREDENTIALS_FILE=/app/secrets/gsheets.json   # local
GOOGLE_SHEETS_CREDENTIALS_JSON=<blob base64>               # Railway
```

⚠️ En Railway **no hay archivo que montar**: va el JSON de la cuenta de
servicio en `GOOGLE_SHEETS_CREDENTIALS_JSON`, en base64 (una sola línea).

Correrlo a mano, contra el documento vivo:

```bash
docker compose exec backend python manage.py import_formativo_gps \
  --file 1WHlhb-K1Pbk1-ttkkCzdIMT69RCfYzXhDyzFXMI4_vo        # dry-run
docker compose exec backend python manage.py shell -c \
  "from exams.tasks import sync_formativo_sheets; print(sync_formativo_sheets(commit=False))"
```

## Los archivos (exports)

Entregados por el club el 2026-09-02. Ruta de referencia:

```
~/Downloads/U de Chile - Formativo/
├── GPS CATEGORÍAS.xlsx                      ~13.000 filas
├── EVALUACIONES FÍSICAS CATEGORÍAS.xlsx     ~10.000 filas útiles
└── Wellness - Check in & Out/               8 archivos, uno por categoría
```

⚠️ Los archivos **no están en el repo** (son datos del club). El runbook asume
que están en esa ruta; ajustar si se mueven.

⚠️ `docker compose exec` no ve el disco del host. Los comandos de Django leen
desde dentro del contenedor, así que cada archivo hay que copiarlo primero —
cada fase indica cómo.

## Orden

Las fases 1→2→3 son estrictamente secuenciales: la 2 consume el CSV de la 1, y
la 3 empareja contra los jugadores que crea la 2. La 4 puede correrse en
cualquier momento antes de la 6. La 6 y la 7 dependen de la 4 (sin plantilla no
hay dónde cargar) y de la 2 (sin jugador no hay a quién).

```
1 (CSV canónico) → 2 (categorías + jugadores) → 3 (pertenencias)
                                    ↓
                        4 (plantillas) → 6 (evaluaciones) → 7 (GPS)
```

---

## Fase 1 — CSV canónico (no toca la base)

Lee los dos libros y emite el maestro. **No escribe en la base**, así que es
seguro correrlo cuantas veces sea.

```bash
python3 backend/scripts/build_formativo_master.py \
  "$HOME/Downloads/U de Chile - Formativo" \
  --season 2026 --outdir "$HOME/Downloads/formativo_fase1"
```

Escribe tres archivos:

| Archivo | Contenido |
|---|---|
| `formativo_maestro.csv` | 417 de plantel + 80 a prueba, con cohorte y fecha |
| `formativo_pendientes.csv` | 9 filas que requieren al club |
| `formativo_historial.csv` | 1207 filas jugador × temporada × bracket, 2024–2026 |

`formativo_alias.csv` sólo aparece si hay renombres que aplicar; hoy no hay
(ver §Defectos conocidos).

**Resultado esperado (2026-09-02):**

```
temporada 2026 · 499 nombres
  plantel (cohorte resuelta) : 417
  cohorte sólo estimada      : 7
  jugadores a prueba         : 80
  sin resolver               : 2
```

**Verificación.** El reparto por serie tiene que reproducir la convención del
club sin que nadie la escriba a mano: Sub 18 = Serie 2009 + 2008, Sub 20 =
Serie 2007 + 2006, y Series 2016–2018 sin bracket ANFP. Correrlo con
`--season 2027` tiene que subir cada serie un peldaño **respetando los huecos**:
Serie 2010 salta Sub 17 y va a Sub 18, Serie 2008 salta Sub 19 y va a Sub 20.

**Revertir:** borrar el `--outdir`. No hay nada más.

---

## Fase 2 — Categorías, jugadores y posiciones

```bash
docker compose cp "$HOME/Downloads/formativo_fase1/formativo_maestro.csv" \
  backend:/tmp/maestro.csv

# Dry-run primero, SIEMPRE. La simulación recorre el mismo camino que el
# commit (escribe y hace rollback), así que el reporte es fiel.
docker compose exec backend python manage.py import_formativo_master \
  --csv /tmp/maestro.csv --club "Universidad de Chile" --season 2026 \
  --top-bucket "SUB-20"

# ... leer el reporte, después:
docker compose exec backend python manage.py import_formativo_master \
  --csv /tmp/maestro.csv --club "Universidad de Chile" --season 2026 \
  --top-bucket "SUB-20" --commit
```

⚠️ **`--top-bucket "SUB-20"` no es opcional.** Sin él el comando crea Serie
2004, 2005, 2006 y 2007 al lado del `SUB-20` que el club ya tiene y que
contiene ese plantel completo — quedan cuatro categorías de 0 a 5 jugadores
compitiendo con la real por las mismas 43 personas. Fue el error de la primera
corrida y hubo que limpiarlo a mano (ver §Limpiezas manuales).

**Resultado esperado:** 165 jugadores creados, 84 actualizados, 4 categorías
nuevas (Series 2015–2018), 1 posición nueva (`EX — Extremo`), 1 `TeamSeason`.
El club pasa de 314 a 479 jugadores en 16 categorías.

**Lo que NO hace sin pedirlo**, y conviene dejar así:

| Flag | Qué habilita | Por qué está apagado |
|---|---|---|
| `--reassign` | Mover jugadores a la categoría de su cohorte | 17 desacuerdos: son el borde del plantel (cohorte 2008 en SUB-20, 2007 en Serie 2008), o sea jugadores que suben. No son errores |
| `--overwrite-dob` | Que gane la fecha del archivo | 13 conflictos, y los tres que el archivo pone en `2006-05-26` tienen en base tres fechas distintas y correctas: la celda está arrastrada |

**Nunca** saca a nadie de una categoría senior, ni con `--reassign`: 12
jugadores del maestro están en Primer Equipo y recategorizarlos por cohorte los
bajaría del plantel.

**Verificación:**

```bash
docker compose exec backend python manage.py shell -c "
from core.models import Club, Category, Player, TeamSeason
from django.db.models import Count
u = Club.objects.get(name='Universidad de Chile')
for c in Category.objects.filter(club=u).annotate(n=Count('players')).order_by('-cohort_year'):
    ts = TeamSeason.objects.filter(team=c, season=2026).first()
    print(f'{c.name:<20} {c.n:<5} {ts.bracket.name if ts and ts.bracket else \"—\"}')
print('total:', Player.objects.filter(category__club=u).count())
"
```

479 jugadores, 16 categorías, **ninguna vacía**.

**Revertir:**

```bash
docker compose exec backend python manage.py shell -c "
from core.models import Club, Player, Category
u = Club.objects.get(name='Universidad de Chile')
# Los creados por la fase 2 son los que no tienen ExamResult ni pertenencia
# previa. Más seguro: restaurar desde un dump anterior a la corrida.
print(Player.objects.filter(category__club=u).count())
"
```

⚠️ No hay revert automático: el comando es aditivo pero no marca lo que creó.
**Tomar un dump antes de correr con `--commit`.**

---

## Fase 3 — Pertenencias con fecha real

```bash
docker compose cp "$HOME/Downloads/formativo_fase1/formativo_historial.csv" \
  backend:/tmp/historial.csv

docker compose exec backend python manage.py backfill_formativo_history \
  --csv /tmp/historial.csv --club "Universidad de Chile" --season 2026
# ... leer, después agregar --call-ups --commit
```

**Resultado esperado:** 159 pertenencias creadas, 16 fechas estimadas
reemplazadas, 219 adelantadas, 56 citaciones **inactivas**, 77 nombres sin
jugador (74 son jugadores a prueba, que la fase 2 no importa: es esperado).

⚠️ `--call-ups` crea las citaciones con `active=False`. Activarlas ensancha el
acceso a datos de menores vía `api.scoping.scope_players`, y concederlo desde
una planilla es un cambio de permisos, no una importación. Las 56 activas que
ya existían (creadas por la UI) no se tocan.

**Verificación:** 469 de 479 jugadores con pertenencia, 394 con motivo
`primera aparición en datos del club`. Los 10 sin pertenencia son 4 de Primer
Equipo (fuera del historial formativo) y 6 sin ninguna aparición fechada.

**Revertir:**

```bash
docker compose exec backend python manage.py shell -c "
from core.models import PlayerTeamMembership as M, PlayerCallUp
M.objects.filter(reason='primera aparición en datos del club').delete()
PlayerCallUp.objects.filter(active=False, note__contains='planilla del club').delete()
"
```

⚠️ Eso borra las 159 creadas, pero **no restaura** las 235 fechas que se
adelantaron. Para eso hace falta el dump.

---

## Fase 4 — Plantillas y aplicabilidad

```bash
docker compose exec backend python manage.py seed_formativo_templates \
  --club "Universidad de Chile" --season 2026
```

Idempotente y sin dry-run: crea o refresca las cinco plantillas, agrega los dos
campos de frecuencia cardíaca a `gps_sesion` y resuelve
`applicable_categories`. Una plantilla bloqueada se salta salvo `--unlock`.

**Resultado esperado:**

| Plantilla | Campos | Categorías |
|---|---|---|
| `carreras` | 21 | 12 (todas) |
| `neuromuscular` | 10 | 12 (todas) |
| `resistencia` | 4 | 7 (Sub 13+) |
| `resistencia_1000m` | 4 | 7 (Sub 13+) |
| `fuerza` | 22 | 7 (Sub 13+) |
| `gps_sesion`, `gps_partido` | +2 FC | 10 (Sub 11+) |

⚠️ **Hay que volver a correrlo al empezar cada temporada.** "Quién hace el
test" se expresa como peldaño ("Sub 13 y más") pero `applicable_categories`
guarda categorías, así que la respuesta cambia todos los años: una Serie 2015
que hoy es Sub 11 será Sub 13 en 2028 y ahí le corresponde Resistencia.

**Verificación:** que las fórmulas calculen por el camino real
(`compute_result_data` se llama en la capa API, **no** en `save()`):

```bash
docker compose exec backend python manage.py shell -c "
from core.models import Club, Player
from exams.models import ExamTemplate
from exams.calculations import compute_result_data
u = Club.objects.get(name='Universidad de Chile')
p = Player.objects.filter(category__club=u).first()
t = ExamTemplate.objects.get(slug='resistencia', department__club=u)
out, _ = compute_result_data(t, {'palier': 51}, player=p)
print(out['metros'], out['vo2_max'])   # esperado: 2040 53.54
"
```

**Revertir:** `ExamTemplate.objects.filter(slug__in=[...]).delete()` borra
también sus `ExamResult` en cascada. Los dos campos de FC en `gps_sesion` hay
que sacarlos del `config_schema` a mano.

---

## Fase 5 — Bandas por categoría ⚠️ A MEDIAS

El **mecanismo** está: una `AlertRule` de tipo BAND puede traer
`config["ranges"]` con sus propios umbrales, y sin eso cae a los del campo, así
que ninguna regla existente cambió. Cubierto por
`backend/goals/test_band_ranges_por_categoria.py`.

⚠️ **Los umbrales del club NO están cargados.** Las hojas
`FORMATO CONDICIONAL 15-16 y 18-` y `FORMATO CONDICIONAL 13 -14 y 11` traen los
cortes reales por categoría (p. ej. "Muy Deficiente" en RM Back Squat es
< 68,3 kg para Sub 13 y < 125 kg para Sub 18) y **nadie las parseó todavía**.
Verificado el 2026-09-02: 0 reglas con `config["ranges"]`, 0 reglas sobre las
cinco plantillas nuevas.

Falta un comando que lea esas dos hojas y siembre una `AlertRule` por
(categoría, campo). Hasta entonces las cinco plantillas nuevas **no generan
ninguna alerta**.

---

## Fase 6 — Evaluaciones físicas

```bash
cp "$HOME/Downloads/U de Chile - Formativo/EVALUACIONES FÍSICAS CATEGORÍAS.xlsx" \
  backend/_formativo_eval.xlsx

docker compose exec backend python manage.py import_formativo_evaluaciones \
  --file /app/_formativo_eval.xlsx
# ... leer, después --commit

rm backend/_formativo_eval.xlsx        # no dejarlo en el árbol de trabajo
```

Aditivo e idempotente: dedup por `result_data["origen_id"]`, nunca sobrescribe.
`--sheet NOMBRE` (repetible) limita a una familia. `--alerts` evalúa alertas de
banda; **apagado por defecto** porque es un backfill 2024–2026 y una alerta
anclada en una lectura de dos años la expira la barrida siguiente.

**Resultado esperado:** 5061 resultados — `carreras` 2119, `neuromuscular`
1413, `resistencia` 853, `fuerza` 666, `resistencia_1000m` 10 — en 396
jugadores, del 2024-01-22 al 2026-07-15.

**Verificación** contra la planilla:

```bash
docker compose exec backend python manage.py shell -c "
from exams.models import ExamResult
from core.models import Club
from collections import Counter
u = Club.objects.get(name='Universidad de Chile')
qs = ExamResult.objects.filter(template__department__club=u,
                               result_data__origen='planilla_club_formativo')
print('total:', qs.count())
for s, n in Counter(qs.values_list('template__slug', flat=True)).most_common():
    print(f'  {s:<20} {n}')
q = qs.filter(template__slug='carreras')
print('t10_best con valor:', sum(1 for r in q.only('result_data')
                                 if r.result_data.get('t10_best') is not None))
"
```

`t10_best` tiene que dar 1297 contra 1338 filas `T10` en el origen, COD 870
contra 876, CMJ 1293 contra 1322. La diferencia son los 16 nombres sin jugador.
Correrlo de nuevo tiene que crear **0**.

**Revertir:**

```bash
docker compose exec backend python manage.py shell -c "
from exams.models import ExamResult
ExamResult.objects.filter(result_data__origen='planilla_club_formativo').delete()
"
```

Limpio y completo — para eso está la clave de procedencia.

---

## Fase 7 — GPS ✅

```bash
cp "$HOME/Downloads/U de Chile - Formativo/GPS CATEGORÍAS.xlsx" \
  backend/_formativo_gps.xlsx

docker compose exec backend python manage.py import_formativo_gps \
  --file /app/_formativo_gps.xlsx
# ... leer, después --commit

rm backend/_formativo_gps.xlsx
```

**Resultado esperado:** 15.352 resultados — 3501 `gps_partido` (1649
vinculados a su evento) y 11.851 `gps_sesion`, 305 jugadores, 2025-01-08 →
2026-09-01. Re-correrlo crea 0.

⚠️ **Los dos avisos del reporte hay que leerlos.** La planilla la mantienen a
mano, así que el importador es a medida de ella y vigila las dos direcciones:

- *"MÉTRICAS QUE NO MAPEARON"* — la hoja cambió de forma y una métrica
  esperada no llegó. Es el bug que ya pasó una vez: el club mete sus umbrales
  en los encabezados (`HSR (m) >20km/h`) y un mapa por string exacto dejó
  cinco de doce métricas afuera, con el reporte diciendo "0 filas sin
  métricas".
- *"Columnas que el importador no reconoce"* — agregaron una columna y se está
  ignorando. Es el riesgo espejo, y el silencioso.

**Revertir:**

```bash
docker compose exec backend python manage.py shell -c "
from exams.models import ExamResult
ExamResult.objects.filter(result_data__origen='planilla_club_formativo_gps').delete()
"
```

### Lo que quedó decidido y medido

- **Se reusa `gps_sesion` / `gps_partido`**, no se crea un tercer examen. Las
  columnas del formativo son un subconjunto estricto: los 13 métricos ya tienen
  campo y `gps_sesion` tiene 16 más que el formativo no usa. La regla de
  exactamente dos exámenes de GPS fue una limpieza deliberada, y los slugs
  están fijos en `api/player_analysis.py`, `api/daily_report.py`,
  `api/player_summary.py`, `api/command_center.py` y la página
  `gps-entrenamiento` del frontend.
- **`LOCALIA` / `CALIDAD OPONENTE` / `RESULTADO` con valor ⇒ es partido** y va
  a `gps_partido`; el resto a `gps_sesion`.
- **Procedencia igual que la fase 6**: `origen`, `origen_hoja`, `origen_id`.
  Sin eso nadie puede distinguir después un HSR de la planilla del club
  (> 20 km/h) de uno de Catapult (> 19,8) — y comparar los dos es exactamente
  lo que el club pidió.
- **`HSR` se trata como equivalente** entre las dos fuentes. Es un **supuesto**
  del cliente, no un hecho verificado (`PLAN_FORMATIVO.md` §3.4). El sesgo es
  sistemático y en una sola dirección: subestima al juvenil.
- Las hojas `U17WC`, `U20 WC` y `WC CLUBES` **se excluyen**: son bitácoras de
  scouting con jugadores de otros equipos (Panamá, Guatemala, Al Ahly, Inter
  Miami). También `Pasing Indi.`, que parte una sesión en bloques de 15
  minutos y contaría el mismo trabajo varias veces.
- **`acc_dec` queda vacío**, igual que en Primer Equipo: Catapult tampoco lo
  llena. Confirmado por el cliente.
- **2174 filas son día de partido sin localía ni resultado** y van a sesión.
  No parecen partidos (mediana 47,0 min y 5180 m, contra 82,2 y 8214 de las
  marcadas) y sin marcas no hay rival ni resultado, así que un `gps_partido`
  sería un registro de partido sin partido.

---

## Fase Wellness — plantillas ✅, importador ⏳

El club confirma que **el wellness del formativo no sigue la misma regla que
el de Primer Equipo**, así que no se reusa `checkin_fisico`: van plantillas
propias. El sync de Google Form sigue alimentando sólo a Primer Equipo (1988
resultados, todos ahí).

### Plantillas — hecho

```bash
docker compose exec backend python manage.py seed_wellness_formativo \
    --club "Universidad de Chile" --season 2026 [--unlock]
```

Crea/actualiza `checkin_formativo` (13 campos) y `checkout_formativo` (16) y
las aplica a las 12 categorías del formativo. Idempotente; `--unlock` hace
falta si alguien bloqueó la plantilla desde el admin.

**Verificación**

```bash
docker compose exec backend python manage.py shell -c "
from core.models import Category
from api import wellness as w
for c in Category.objects.filter(club__name='Universidad de Chile'):
    print(c.name, w.roles_for(c), [t.slug for t in w.templates_for(c)])"
```

Primer Equipo tiene que dar `['checkin'] ['checkin_fisico']` y cada Serie
`['checkin', 'checkout'] ['checkin_formativo']`.

### La plantilla declara su escala

`config_schema["wellness"]` lleva `role` (`checkin`/`checkout`), `items` (lo
que promedia el puntaje 0–100), `inverted` y `dimensions` (los chips del KPI).
`api/wellness.py` los lee; ninguna superficie tiene el slug hardcodeado.

⚠️ **Usar `score_for(category, data)`, nunca `score()` a mano.** Tres de los
cinco ítems del formativo están invertidos y acertar los ítems pero errar los
invertidos da un puntaje exactamente al revés: un jugador destruido puntúa 84.

⚠️ Una dimensión declarada que **no** sea también ítem del puntaje necesita que
`field_max` la cubra, o `dimension_pct` devuelve `None` y el chip no aparece
sin ningún error. Eso lo resuelve `_claves()`; si se agrega otro lookup por
campo, tiene que usarlo.

⚠️ La fracción es `v ÷ max`, **no** un reescalado min–max: el peor valor
posible de una escala 1–5 vale 20, no 0. Es la misma propiedad que hace que el
peor check-in de Primer Equipo dé 18. Cambiarla movería todos los números
históricos de los dos planteles.

### Importador ⏳ pendiente

Los 8 documentos (65.067 filas de CHECK IN + 53.040 de CHECK OUT) siguen sin
importar, y falta su cron. Notas para escribirlo:

- El match es **por nombre**: el orden de columnas cambia entre documentos.
- Alias de encabezado: `CALIDAD SUEÑO`/`CALIDAD DEL SUEÑO`,
  `Peso (kg)`/`Peso (kg) solo número`.
- La categoría sale del **título del documento**: `CAT 15` → cohorte 2015;
  `SUB 21` → bracket Sub 20.
- `SUMA` y `UA` **no se importan** — los calcula la plantilla. Sus encabezados
  son inconsistentes (`SUMA` en cuatro documentos, un `0` pelado en uno, `UA`
  en seis y `AU` en uno).
- Reusar `exams/formativo_sources.py`: resuelve el título truncado a 31
  caracteres, pide `UNFORMATTED_VALUE` (el punto es separador de miles) y
  convierte seriales a fecha **sólo en columnas de fecha**.

Falta decidir si el formulario va a cubrir el formativo de acá en adelante —
porque si no, importar el histórico deja una serie que se corta el día de la
carga.

---

## Limpiezas manuales que hubo que hacer

Documentadas porque una corrida desde cero **no** las necesita, y verlas en el
historial sin explicación confunde.

**Series 2004–2007 creadas por error** (2026-09-02). La primera corrida de la
fase 2 fue sin `--top-bucket`, así que creó cuatro categorías que duplicaban al
`SUB-20`. Se movieron sus 12 jugadores al `SUB-20` (que quedó en 55) y se
borraron las cuatro categorías y sus dos `TeamSeason`. Con `--top-bucket` desde
el principio no ocurre.

---

## Defectos conocidos

- **`NAME_FIX_BY_DOB` es código muerto** en `build_formativo_master.py`.
  `CLUB_CONFIRMED` está indexado por nombre y corre antes, así que le cambia la
  fecha y la clave `(nombre, fecha)` nunca coincide. Los dos David Guzmán
  quedaron bien separados igual —`BASCUR` 2011-02-10 Serie 2011 y `VIVANCO`
  2008-06-09 Serie 2008, posiciones incluidas— pero por las hojas de sesión,
  que sí traen el apellido correcto, no por ese mecanismo. Si el club alguna vez
  entrega los datos sin ese respaldo, la corrección no va a actuar.
- **`implied_cohort` no sirve en los brackets altos.** La inversión
  etiqueta→cohorte sólo vale cuando el jugador juega su propio peldaño; en Sub
  18 y Sub 20 no hay a dónde subir, así que un jugador que se queda ahí varias
  temporadas invierte a una cohorte móvil (248 de 501 lo muestran). Se usa sólo
  para los 7 sin fecha de nacimiento y va marcada como estimación.
- **`seed_fatiga_central` filtra por `Category.departments`**, y en este club
  sólo `Primer Equipo` los tiene vinculados: su plantilla probablemente aplica
  sólo a Primer Equipo. Es el mismo bug que tuvo la fase 4 y que ahí se
  corrigió. No se tocó porque es de otro departamento.
- **Ninguna categoría formativa tiene `Category.departments` poblado.** No
  bloquea exámenes —`applicable_categories` es la puerta que lee la API— pero
  vacía la lista de departamentos del reporte diario para esas categorías.

---

## Pendiente del club

| Qué | Cuánto | Dónde |
|---|---|---|
| Fechas de nacimiento | 9 | `formativo_pendientes.csv` |
| Filas sin fecha de sesión | 200 | 119 en `PRESS DE BANCO` (la hoja no tiene columna de fecha), 62 en `1000 METROS` |
| Nombres sin jugador | 16 | typos (`DAMINA SOLIS`) y filas con sólo apellido (`OLIVEROS`, `CORNEJO`) |
| Celdas con valores imposibles | 7 | listadas por el importador; incluyen un `v_60kg=45992` (número de fecha) y un T30 de 2,68 s |
| Fechas arrastradas | 2 | `2012-01-04` en 4 jugadores, `2006-05-26` en 3 |
| Desacuerdos de categoría de un año | 10 | reportados por la fase 2 |
