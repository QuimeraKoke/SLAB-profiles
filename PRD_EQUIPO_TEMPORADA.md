# PRD — Equipo y temporada (cohortes) en lugar de categoría mutable

**Estado:** propuesta · **Fecha:** 2026-08-22 · **Origen:** hallazgos de la carga COMET
de juveniles (ver `STATUS.md` §3.52 y `project_comet_integration`).

---

## 1. El problema, medido

`core.Category` cumple hoy dos roles incompatibles: es **el grupo de trabajo** del club
y a la vez **la categoría de competencia**. Mientras el club tuvo una sola temporada
cargada nadie lo notó. Con dos temporadas de datos oficiales, el conflicto es medible:

| Temporada | Participaciones juveniles | Coincide `player.category` con `event.category` |
|---|---|---|
| 2025 | 3.032 | **93,6 %** |
| 2026 | 1.968 | **16,8 %** |

Las etiquetas **no están mal: están congeladas en 2025**. Los nacidos en 2014 figuran
como `SUB-11`, que era correcto en 2025 y en 2026 ya es `Sub 12`.

El punto central, y la razón por la que este PRD existe en lugar de un `UPDATE`:

> **Un solo campo `Player.category` no puede describir dos temporadas a la vez.**
> Rotar las etiquetas una posición arregla el 16,8 % de 2026 y rompe el 93,6 % de
> 2025 — que además tiene más datos. Y en enero de 2027 se vuelve a desfasar, porque
> una rotación manual no instala un mecanismo.

### 1.1 Lo que el modelo actual ya no puede responder

Estas preguntas hoy requieren reconstruir la historia desde `EventParticipant`,
porque `Player.category` sólo conoce el presente:

- ¿Cómo evolucionó **este grupo de jugadores** a lo largo de tres temporadas?
- ¿Qué jugadores **saltaron de equipo** y cuándo?
- ¿Este chico jugó **por encima de su cohorte**, y en qué temporada empezó?

La reconstrucción funciona (§6) pero es frágil: depende de que existan participaciones
cargadas, y se pierde para cualquier jugador cuyo `category` haya sido editado.

### 1.2 Lo que sí es real y hay que conservar

El 26,1 % de las apariciones juveniles de 2026 son chicos jugando **por encima** de su
cohorte. Ése es el préstamo genuino y es alto de forma sana. No hay que "arreglarlo":
hay que poder medirlo. La lectura por etiqueta daba 85–100 %, que era ruido de
corrimiento, no préstamo.

---

## 2. Modelo propuesto

Tres entidades donde hoy hay una.

### 2.1 `Team` — el cohorte (persistente)

El grupo de personas que avanza junto en el tiempo. Identidad estable, etiqueta que
**nunca se vence**: `Serie 2012`, no `SUB-14`.

```
Team
  club            FK Club
  cohort_year     int          # 2012 — la identidad real
  name            str          # "Serie 2012" (derivable, editable)
  departments     M2M Department
  active          bool
```

Físicamente **es la tabla `core_category` renombrada**, con `cohort_year` agregado. Esto
es deliberado: hay 146 sitios que filtran `category=`, 67 con `category__` y 51 con
`player__category`. Reusar la tabla mantiene todos funcionando durante la transición.

Los equipos no-cohorte (`Primer Equipo`, femenino) llevan `cohort_year = NULL` y se
comportan como hoy.

### 2.2 `Bracket` — la categoría de competencia

Lo que publica la federación: `Sub 11, 12, 13, 14, 15, 16, 18, 20, Primera`.
Independiente de la temporada y del club.

⚠️ **La ANFP no tiene Sub 17 ni Sub 19.** La escalera real es
`11→12→13→14→15→16→18→20→Primera`. Todo cálculo de progresión debe usar esta escalera:
tratar 16→18 como "salto de dos" es un error que ya cometí dos veces al analizar estos
datos.

### 2.3 `TeamSeason` — el puente

Para la temporada Y, el equipo T compite en el bracket B.

```
TeamSeason
  team            FK Team
  season          int
  bracket         FK Bracket
  external_config JSON     # ← se muda acá desde Category
  unique (team, season)
```

Derivable de `season - cohort_year` mapeado al primer bracket existente, pero
**declarado y editable**: la derivación acierta en 86–100 % según cohorte, y el club
debe poder corregir el resto sin pelear con una fórmula.

`Category.external_config` **ya contiene `season`** (el binding de API-Football), lo que
confirma que la temporada quiere vivir en esta tabla y no en la categoría.

### 2.4 `PlayerTeamMembership` — la pertenencia con fecha

La pieza que hace posible todo el análisis de desarrollo. Sin ella, un traspaso borra
que el jugador alguna vez estuvo en otro equipo.

```
PlayerTeamMembership
  player          FK Player
  team            FK Team
  since           date
  until           date NULL      # NULL = vigente
  reason          str            # "traspaso", "carga inicial", …
```

`Player.category` **se conserva** como puntero al equipo vigente (denormalizado) para
no romper los ~280 sitios de consulta. La membresía es la fuente de verdad; el puntero
se mantiene con un signal.

### 2.5 El préstamo se calcula, no se declara

`PlayerCallUp` sigue existiendo, pero su semántica queda anclada al cohorte y no a la
etiqueta: **hay préstamo cuando el jugador aparece en un bracket superior al de su
equipo en esa temporada**. Ya está implementado así (`comet_sync._sync_call_up`,
commit `639e1d4`) y da 26 % en lugar del 85–100 % que daba la comparación por etiqueta.

---

## 3. Impacto por subsistema

Esta sección **es parte del alcance**, no un anexo. Cada punto es trabajo a hacer o
riesgo a resolver.

### 3.1 Eventos y calendarios — 🔴 el cambio más profundo

Hoy `Event.category` apunta a la categoría SLAB. Con cohortes eso deja de funcionar,
porque **un partido de Sub 18 lo juegan dos equipos a la vez**: los de 2009 y los de
2008 (96,1 % y 63,4 % de sus apariciones respectivamente). Un solo FK no los representa.

- `Event.bracket` (nuevo) = la competencia. Es lo que COMET ya entrega y lo que el sync
  ya resuelve.
- `Event.category` se conserva durante la transición apuntando al equipo principal
  (el cohorte dominante), para no romper el calendario existente.
- La consulta del calendario cambia de `event.category = mi_categoría` a
  *"eventos del bracket donde mi equipo compite esta temporada"*, o sea un join por
  `TeamSeason`. **Esto altera qué ve cada usuario en su calendario** y es el punto que
  necesita más cuidado en QA.
- Los 297 eventos juveniles de 2025 y los 155 de 2026 ya cargados quedan con su
  categoría actual; el backfill de `bracket` se deriva del nombre + temporada.

**A resolver:** ¿un evento de Sub 18 aparece en el calendario de los dos equipos, o
sólo en el del cohorte principal con los demás como invitados? Afecta asistencia y
citaciones.

### 3.2 Exámenes — 🟢 impacto bajo, y a favor

`ExamTemplate.applicable_categories` (M2M) se resuelve en runtime en ~10 lugares:
`daily_report`, `command_center`, `export`, `alert_rules`, `triage`, `wellness`,
`goals.models`. Los exámenes se administran al **grupo de trabajo**, no al bracket, así
que el M2M se queda apuntando a `Team` y **no cambia nada**.

Beneficio lateral: hoy la plantilla se liga a una etiqueta que se vence, así que cada
temporada habría que re-vincular. Con cohortes se liga una vez.

⚠️ Excepción: `ficha_partido` es por definición del bracket (es la ficha oficial del
partido). Hoy está ligada sólo a `Primer Equipo` y el sync **no consulta**
`applicable_categories`, así que escribe igual. Conviene dejarlo explícito en el
modelo en vez de que funcione por omisión.

### 3.3 Reportes de equipo y dashboards — 🟡 revisar semántica

Modelos afectados: `DashboardLayout`, `TeamReportLayout`, `TeamReportSnapshot`,
`BriefingSnapshot`, `DailySummary` — todos con FK a `Category`.

- Como layouts pertenecen al grupo de trabajo, pasan a `Team` sin cambio funcional.
- `resolve_team_widget` ya distingue propios de citados: incluye a los citados por
  defecto (`include_secondary=True`) y los marca vía `call_up_player_ids`. **Esa
  semántica ya es la correcta para este modelo** y no hay que tocarla.
- ⚠️ Pero otras superficies usan `category=` plano, que excluye citados por
  construcción (p. ej. `team_aggregation.py:2795`). Con el préstamo al 26 % eso puede
  dejar fuera a un cuarto del plantel real sin avisar. **Hay que auditar los 146 sitios
  `category=` y decidir en cada uno si quiere "grupo de trabajo" o "plantel que jugó".**
  Es el trabajo más tedioso del proyecto y el que más errores silenciosos puede dejar.

### 3.4 Integraciones — 🟡 dos anclajes que se mudan

- **COMET** (`CometIntegration`, por club): ya resuelve el bracket desde la competencia
  y mapea a categoría vía `_category_index`. Ese mapeo pasa a `Bracket` + `TeamSeason`
  y **se simplifica**: hoy adivina por token de edad contra la etiqueta de SLAB, que es
  justo lo que está desfasado.
- **Catapult** (`CatapultIntegration.category`, FK): es por grupo de trabajo → `Team`.
  Sin cambio semántico.
- **API-Football** (`Category.external_config` con `season`): se muda a `TeamSeason`,
  que es su lugar natural. Deja de haber que editar la categoría cada temporada.
- **VALD** (`ValdIntegration` por club, matching por `ValdProfileLink`): no toca
  categoría. Sin impacto.

### 3.5 Permisos y scoping — 🟡 verificar, no cambiar

`api/scoping.py` ya modela exactamente lo que necesitamos: acceso = categorías
asignadas ∪ citaciones activas, y conteos sólo por categoría propia. Con `Team` en
lugar de `Category` la lógica es idéntica.

⚠️ **Cuidado con el volumen.** La tabla `PlayerCallUp` estuvo **vacía** hasta el
2026-08-20, y el docstring del modelo dice que una tabla vacía significa cero cambio de
comportamiento. Al poblarla se activa el ensanchamiento de acceso y el distintivo en
planteles. Ya pasó una vez con 167 filas de las cuales 117 eran ruido. Cualquier
generación automática de citaciones debe medirse antes de escribirse.

### 3.6 Alertas y objetivos — 🟢 bajo

`goals` tiene 7 sitios con categoría y valida que la plantilla aplique a la categoría
del objetivo (`goals/models.py:377`). Sigue funcionando con `Team`.

### 3.7 Frontend — 🟡 principalmente etiquetas

- `CategoryProvider` en el layout de `(dashboard)` y 31 sitios que consumen
  `useCategoryContext`. El selector global sigue eligiendo un **equipo**; sólo cambia
  el texto que muestra.
- 16 referencias a `category` en `lib/types.ts`.
- **A definir:** ¿el selector global ofrece equipos (`Serie 2012`) o brackets
  (`Sub 14`)? Recomendación: equipos, porque es lo que el cuerpo técnico habita a
  diario, con el bracket visible como dato derivado. Esto toca la regla de IA nº 3 de
  `AGENTS.md` ("una etiqueta = un significado"): `Categoría` deja de ser un término
  único y hay que nombrar `Equipo` y `Categoría de competencia` distinto en toda la UI.

### 3.8 Histórico 2025 — 🔴 decisión de producto

Ningún camino es gratis:

- **No mover a nadie** (renombrar solamente): 2025 y 2026 quedan ambos legibles porque
  la categoría pasa a significar "cohorte" y el bracket se deriva por temporada. Es la
  opción que este PRD recomienda.
- **Rotar las etiquetas**: rompe 3.032 participaciones de 2025.

Con `TeamSeason` el histórico se lee correcto en las dos temporadas **sin tocar ninguna
fila de jugador**, que es el argumento principal a favor de este modelo.

---

## 4. Migración por fases

| Fase | Contenido | Riesgo |
|---|---|---|
| 0 | `Bracket` + `TeamSeason` + `Team.cohort_year`. Nada los consume todavía. | nulo (aditivo) |
| 1 | Backfill: `cohort_year` desde el año de nacimiento dominante; `TeamSeason` para 2025 y 2026 desde las participaciones reales. Verificar contra §6. | bajo (datos nuevos) |
| 2 | Renombrar equipos a etiqueta de cohorte. `PlayerTeamMembership` con la carga inicial. | bajo, reversible |
| 3 | `Event.bracket` + backfill. Calendario lee por `TeamSeason`. **QA fuerte acá.** | 🔴 alto |
| 4 | Auditar los 146 `category=` uno por uno. | 🔴 alto, tedioso |
| 5 | Mudar `external_config` a `TeamSeason`. Simplificar el mapeo de COMET. | medio |
| 6 | UI: nombres nuevos, selector, distinción Equipo / Categoría de competencia. | medio |

Fases 0–2 se pueden hacer sin que nada cambie de comportamiento. La 3 y la 4 son el
proyecto real.

---

## 5. Fuera de alcance

- Rotación automática de temporada (con `TeamSeason` declarado ya no hace falta).
- Femenino: sin competencias en el feed de COMET; se comporta como hoy.
- **Cargar el cohorte 2015** (Sub 11 2026): el club no tiene ningún jugador de 2015 en
  SLAB, así que esos 6 partidos ya cargados tienen cero fichas. Es dato del club, no
  código.
- `SUB-17` queda huérfana (la ANFP no tiene ese bracket; hay 2 jugadores ahí).

---

## 6. Feature: análisis de desarrollo y saltos

El modelo habilita esto como consulta directa en lugar de reconstrucción. Resultado
sobre los datos actuales (153 jugadores con ≥3 partidos en ambas temporadas):

| Situación 2026 | Jugadores |
|---|---|
| ★ Muy por encima de su cohorte (+2) | 1 |
| Por encima (+1) | 8 |
| En su cohorte | 143 |
| Por debajo (−1) | 1 |

Casos destacados: **Jhon Cortés** (2008) llegó a Primera, dos escalones sobre su
cohorte; **Marthin Fuentes** (2012) es el único de las categorías chicas que se
adelanta, con 18 partidos en Sub 15.

### 6.1 Dos trampas de medición, aprendidas a golpes

1. **No comparar el nivel de una temporada contra la otra.** Mezcla la progresión
   natural de la escalera con la posición del jugador respecto de su cohorte. Con ese
   método, cuatro nacidos en 2008 aparecían "retrocediendo" de Sub 20 a Sub 18 cuando
   simplemente volvieron a su nivel tras haber jugado arriba.
2. **La vara se mueve por los huecos de la escalera.** Un nacido en 2007 está "+1" a
   los 18 (bracket natural Sub 18, juega Sub 20) y "+0" a los 19 (su natural pasa a ser
   Sub 20) **jugando exactamente lo mismo**. Eso generó 16 falsos "dejó de
   adelantarse". La vara correcta es el bracket del cohorte vía `TeamSeason`, no la
   edad nominal.

Y una regla operativa: **descartar muestras de menos de 3 partidos por temporada.** Sin
ese filtro aparecen "saltos" de jugadores con una sola aparición.

---

## 7. El ancla: cohorte del jugador, no bracket del equipo

**Descubierto validando la fase 1 en local (2026-08-22), y corrige el criterio de
aceptación original de este PRD.**

`TeamSeason.bracket` describe correctamente al **equipo como grupo**, pero no puede
ser correcto para cada jugador de un equipo mixto. SUB-15 tiene 30 chicos de 2010 y
unos pocos de 2011: su bracket de equipo es Sub 16 por dominancia, así que los de 2011
aparecen jugando "por debajo" de su equipo cuando en realidad están exactamente donde
les toca.

Medido sobre las mismas participaciones, con las dos anclas:

| Ancla | 2025 en su bracket | 2026 en su bracket | Juega abajo (2026) |
|---|---|---|---|
| Bracket del **equipo** | 94,5 % | 86,5 % | **8,7 %** |
| Cohorte del **jugador** | 89,7 % | 88,9 % | **0,7 %** |

Dos razones por las que gana el cohorte:

1. **Jugar abajo es anómalo por definición** — salvo los casos de fecha de corte, nadie
   tiene sobre-edad para un bracket. El ancla por cohorte deja 0,7 %; la del equipo
   inventa un 8,7 % que no son préstamos ni errores, sino equipos mezclados.
2. **Es estable entre temporadas** (89,7 → 88,9). La del equipo cae 8 puntos porque los
   equipos de 2026 están más mezclados que los de 2025. Una métrica correcta no debería
   moverse así entre dos temporadas normales.

**Regla:** `TeamSeason` es la verdad para *"¿en qué compitió este equipo?"* —
calendarios, fixtures, bindings de proveedor. Cualquier juicio **sobre un jugador**
(préstamo, desarrollo, jugar arriba) usa su año de nacimiento. Es lo que ya hace
`comet_sync._sync_call_up`.

> Nota sobre denominadores: el 26 % de préstamo citado en §1.2 se mide sobre fichas
> juveniles; el ~10 % de esta tabla, sobre todas las participaciones incluyendo Primer
> Equipo, que diluye. No se contradicen.

---

## 8. PENDIENTE — Detección de talento con variables físicas

**Estado: bloqueado por datos, no por código.** El código está escrito, probado y
desplegado en local; espera GPS juvenil para tener con qué trabajar.

### Por qué está bloqueado

De los **42 jugadores que juegan por encima de su cohorte, sólo 10 tienen GPS —
y los 10 ya están en Primer Equipo.** Ninguna categoría juvenil tiene una sola
fila: las 6.331 del club son de Primer Equipo (4.147) y Selección Nacional
(2.184). `CatapultIntegration` está habilitado únicamente para Primer Equipo.

Dicho de otro modo: hoy el detector vería sólo a quienes ya fueron promovidos,
que es exactamente donde la pregunta ya está contestada. La señal falta donde
más valdría — Marthin Fuentes, Oscar Belmar, Benjamin Garcés: cero filas.

### Qué se necesita para desbloquearlo

**No hace falta Catapult.** 5.830 de las 6.331 filas existentes entraron por
carga manual, no por la integración, y `/gps-entrenamiento` ya la soporta. Es un
proceso que el club puede arrancar sin una línea de código.

Umbral de utilidad, derivado de lo medido en §8.2: por categoría juvenil hacen
falta **≥ 8 jugadores por sesión** (para que haya pares comparables) y
**≥ 3 apariciones por jugador** en la temporada. Con menos, el análisis va a
responder "sin datos suficientes", que es correcto pero inútil.

### Qué ya está construido

- `api.development.physical_context(player, season)` — compara contra el plantel
  con el que jugó, en los mismos partidos, así rival y ritmo quedan controlados.
- `GET /api/players/{id}/physical-context` — respeta `scope_players`.
- Tests en `api/test_development.py` que fijan las decisiones de abajo.
- Falta sólo: enchufarlo a la pantalla `/desarrollo` (panel por jugador).

### 8.1 Las dos confusiones ya resueltas — no re-derivarlas

Ambas medidas sobre datos reales, ambas producen números falsos con cara de
precisos:

| Trampa | Evidencia |
|---|---|
| Las métricas **acumuladas** miden MINUTOS, no capacidad | Jhon Cortés daba percentil **13** en distancia total y **17** en HSR sólo porque entró a los 10 minutos |
| Las tasas **por minuto** favorecen entradas cortas | Vicente Ramírez pasó de percentil **30 a 55** en velocidad máxima al comparar contra minutos parecidos; su número bajo era el artefacto |

De ahí: sólo `max_vel`, `mpm`, `hsr_min`, `sprint_dist_min` (fijado por test, con
`tot_dist`/`hsr`/`sprint_dist`/`player_load` explícitamente excluidas), y pares
acotados a **±35% de la duración típica del propio jugador**.

Y una tercera que conviene tener presente: **comparar GPS crudo entre edades no
dice nada.** Un 2008 le corre a un 2014 por construcción. La comparación tiene
que ser contra el plantel con el que jugó, o percentil dentro de su propio
cohorte — nunca absoluta.

### 8.2 La consecuencia incómoda

Acotar bien **derrumba la muestra justo en los casos interesantes**: Cortés queda
con UN par comparable. Un "percentil 100 (n=1)" es ruido disfrazado de señal, así
que por debajo de `MIN_PEERS = 8` la función devuelve los valores crudos **sin
percentil**, con el motivo. Barrera, que juega 98 minutos, tiene 189 pares y sí
se puede juzgar.

Esa es la razón de fondo por la que esto queda pendiente en vez de "listo": la
función es correcta, pero con los datos de hoy responde "sin datos suficientes"
para casi todos los juveniles, y preferimos eso a un número que haga tomar una
decisión sobre un chico comparándolo con un solo compañero.

### 8.3 Cuando haya datos, la señal a construir

El talento no es una métrica, es una **conjunción**: juega por encima de su
cohorte (§7) **y** sostiene el nivel físico del grupo mayor con el que juega
(§8). El primer término ya está medido y en pantalla; el segundo espera GPS.

El caso a vigilar en la otra dirección es igual de valioso: un chico que juega
arriba pero **no** sostiene el físico está siendo empujado demasiado rápido, y
eso hoy no lo ve nadie.

---

## 9. PENDIENTE — Bio-banding y proyección de talla

A diferencia de §8, esto **no está bloqueado por falta de datos**: la
antropometría juvenil existe, es seriada y está completa. Lo que falta es un
arreglo de datos, una medición nueva y el código.

### 9.1 Lo que YA hay (verificado 2026-08-22)

`pentacompartimental` (Nutricional) cubre **332 jugadores y 2.388 mediciones**,
juveniles incluidos, desde 2024-05. Y trae los tres campos que importan:

| Campo | Completitud en juveniles |
|---|---|
| `talla` | 1.185 / 1.185 (100 %) |
| `talla_sentado` | 1.185 / 1.185 (100 %) |
| `peso` | 1.185 / 1.185 (100 %) |

Mediciones seriadas por categoría: SUB-11 (29 jugadores, 89 mediciones) hasta
SUB-20 (43, 311). Unos 160 jugadores tienen ≥6 meses de recorrido y ~45 tienen
≥12 meses.

**Talla + talla sentado + peso + edad es exactamente el insumo de la ecuación de
Mirwald** (maturity offset, años desde el pico de velocidad de crecimiento). O
sea que el corazón del bio-banding **es computable hoy**, sin pedirle nada a
nadie.

### 9.2 ⚠️ BLOQUEANTE: 20 filas con las columnas corridas

Antes de calcular cualquier cosa hay que arreglar esto, porque produce
velocidades de crecimiento absurdas (SUB-11 promediaba **+62 cm en 4 meses**).

20 filas tienen `talla` por debajo de 100 cm, mínimo **30,25**. Mirando las tres
columnas juntas el patrón es inequívoco — están **corridas un lugar**:

| Campo | Valor guardado | Lo que realmente es |
|---|---|---|
| `peso` | 11,0 · 15,0 | la EDAD |
| `talla` | 30–68 | el PESO en kg |
| `talla_sentado` | 131–179 | la TALLA de pie |

Afecta dos lotes concretos: **SUB-11 el 2025-04-07 (10 filas)** y **SUB-14 el
2026-03-30 (9 filas)**, más 1 en SUB-15. Viene de `import_pentacompartimental`
con un desalineamiento de columnas en esos archivos.

No lo corregí por inferencia: el mapeo se ve claro, pero reescribir datos
adivinando la columna de origen es peor que dejarlos marcados. **Hay que
re-importar esos dos lotes desde el xlsx original.**

Consulta para encontrarlas:

```sql
SELECT p.first_name, p.last_name, r.recorded_at::date,
       r.result_data->>'talla', r.result_data->>'talla_sentado', r.result_data->>'peso'
FROM exams_examresult r
JOIN exams_examtemplate t ON t.id=r.template_id AND t.slug='pentacompartimental'
JOIN core_player p ON p.id=r.player_id
WHERE (r.result_data->>'talla') ~ '^[0-9.]+$'
  AND (r.result_data->>'talla')::numeric < 100;
```

Y conviene una validación de rango en el importador: una talla fuera de
100–220 cm no es un dato, es un error de columna.

### 9.3 Los dos métodos, y qué necesita cada uno

**A. Maturity offset (Mirwald) — feasible YA.** Estima los años que faltan (o
sobran) para el pico de velocidad de crecimiento a partir de edad, talla, talla
sentado y peso. Con eso se agrupa por madurez en vez de por año de nacimiento,
que es el bio-banding propiamente dicho.

**B. Porcentaje de talla adulta predicha (Khamis-Roche) — necesita un dato
nuevo.** Es el método estándar para bandear por %PAH (85–90 %, 90–95 %…), y
requiere **la talla de los padres** (mid-parental height), que no está en ningún
template. Es una medición que se pide una vez por jugador y no cambia nunca —
buen candidato para un campo en la ficha en lugar de un examen.

**C. Proyección desde la propia curva.** Con talla seriada se estima velocidad de
crecimiento (cm/año) y se ubica al chico antes, durante o después del PHV. No
predice talla adulta como Khamis-Roche, pero sí responde "¿está en pleno
estirón?", que es lo que cambia la carga de entrenamiento. Necesita **≥12 meses
de recorrido**: hoy lo cumplen ~45 jugadores, y crece solo con el tiempo.

### 9.4 Alcance real, medido (2026-08-22)

Implementado y validado. Dos hallazgos que **acotan** la función, y conviene
tenerlos antes de diseñar pantalla:

**El APHV de Mirwald se sesga hacia la edad actual.** La mediana deriva
**+1,19 años** entre los 10 y los 17, mientras la dispersión dentro de una misma
edad es de ~0,55. La deriva es más del doble de la señal. Consecuencia concreta:
un APHV de 14,0 es TEMPRANO para un chico de 17 (mediana 14,46) y TARDÍO para uno
de 14 (mediana 13,38) — el mismo número significa lo opuesto. **Clasificar contra
un umbral de literatura mediría sobre todo la edad.** Por eso `maturity_timing`
exige la lista de pares de la misma edad y se abstiene con menos de 8.

**El bio-banding sólo informa de SUB-12 a SUB-15.** Cruzando banda de madurez
contra categoría cronológica:

| Equipo | Lejos del pico | Acercándose | Recién pasado | Pasado | Bandas |
|---|---|---|---|---|---|
| SUB-11 | 29 | 0 | 0 | 0 | 1 |
| SUB-12 | 17 | 8 | 0 | 0 | 2 |
| **SUB-13** | 3 | 12 | 14 | 3 | **4** |
| SUB-14 | 0 | 2 | 9 | 21 | 3 |
| SUB-15 | 0 | 1 | 2 | 29 | 3 |
| SUB-16 y más | 0 | 0 | 0 | todos | 1 |

SUB-13 tiene 32 chicos de la misma edad en las cuatro bandas: ahí el bio-banding
cambia una decisión. De SUB-16 hacia arriba están todos pasados del pico y las
bandas colapsan a una, así que una pantalla que ofrezca bandas para SUB-18
promete algo que el dato no tiene.

Validaciones que dan confianza en la implementación: el offset mediano por
cohorte sale perfectamente monótono (SUB-11 −2,40 → SUB-18 +3,01), la edad
estimada del pico cae en **13,4–14,5 años** —el rango publicado para varones,
sobre una ecuación ajustada en otra población— y la clasificación reparte 32
tempranos / 143 normales / 36 tardíos, o sea 15 % y 17 % en las colas, que es lo
que produce un umbral de ±1 desviación.

### 9.5 Por qué esto importa junto con §7 y §8

El bio-banding responde la objeción más fuerte al análisis de cohorte de §7: un
chico que juega por encima de su edad puede estar simplemente **madurando antes**,
no siendo mejor. Y al revés — el caso que hoy nadie ve — un jugador de maduración
tardía que rinde en su propia categoría puede ser el más talentoso del grupo, y
el sistema actual lo lee como promedio.

Con las tres piezas juntas la lectura cambia de "juega arriba" a "juega arriba
**para su nivel de madurez**", que es una afirmación completamente distinta y
mucho más difícil de fabricar.

⚠️ Advertencia de método, en la línea de §7 y §8.1: **agrupar por madurez no
justifica comparar GPS crudo entre bandas.** Todo lo de §8.1 sigue aplicando —
métricas por minuto, pares de duración comparable, y negarse a dar percentiles
sobre muestras chicas.

---

## 10. Criterios de aceptación

1. **Participaciones en el bracket natural del jugador ≥ 88 %** en ambas temporadas, y
   **"juega abajo" ≤ 1 %**. Alcanzado en la fase 1: 89,7 % / 88,9 % y 0,9 % / 0,7 %.
   *(El criterio original pedía ≥ 95 % contra el bracket del equipo; §7 explica por qué
   esa vara era la equivocada.)*
2. Para el mismo dato, la coincidencia por **equipo** pasa de 16,8 % a **86,5 %** en
   2026 sin mover ninguna fila de jugador, y 2025 no se degrada (93,6 → 93,9 %).
3. El préstamo medido no salta a 85–100 %: ese salto es la firma de que algo volvió a
   comparar etiquetas en lugar de cohortes.
4. Ningún jugador cambia de `Player.category` durante las fases 0–2.
5. El calendario de cada equipo muestra los partidos de su bracket de la temporada, y
   los partidos compartidos (Sub 18 con dos cohortes) aparecen resueltos según la
   decisión de §3.1.
6. Los 146 sitios `category=` quedan clasificados explícitamente como "grupo de
   trabajo" o "plantel que jugó".
