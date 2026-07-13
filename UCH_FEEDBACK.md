# SLAB × Universidad de Chile — Respuesta a las Sugerencias de Mejora

> **Documento de trabajo.** Fuente: `Sugerencias_Plataforma_SLAB_UCH.pdf`
> (Dr. Diego Molina Solivelles, Depto. Ciencias del Deporte + Área Médica, julio 2026).
>
> **Enfoque acordado (2026-07-12):** resolver cada solicitud como **configuración
> self-service** — *"el club es dueño del parámetro"* — en vez de un cambio
> hardcodeado por cada pedido. Construimos la perilla una vez; el club la ajusta
> para siempre.

## Cómo leer este documento

- **Parte 1** — cada **solicitud** del Dr. Molina → *estado actual en el código*
  → *solución propuesta* → *config vs. código* → *fase*.
- **Parte 2** — **todos los cambios** consolidados por fase, en formato checklist:
  el backlog sobre el que empezamos a trabajar.

## Decisiones ya tomadas

- **UX de configuración = híbrido.** Editores *in-app* para las perillas de uso
  frecuente (umbrales/alertas + widgets de panel); Django admin *endurecido*
  (formularios estructurados, no JSON crudo) para lo estructural (plantillas de
  examen, parámetros de cómputo, etapas de lesión).
- **Gobernanza = rol Editor + barandas.** Solo el grupo **Editor** edita config;
  protegido por validación + **previsualización/backtest** + versionado + auditoría.

## Primitivas reutilizables (la base self-service)

Casi todas las solicitudes se apoyan en unas pocas piezas comunes. Cada solución
más abajo referencia estas primitivas por número.

| # | Primitiva | Qué ya existe | Qué falta |
|---|-----------|---------------|-----------|
| **P1** | **Motor de reglas configurable** (`AlertRule` extendido) | kinds `bound`/`variation`/`band`; evaluador; barridos de caducidad | GPS desconectado (sin `reference_ranges`); sin scope por `tipo_sesion`/posición/microciclo; sin kinds Z-score / % demanda / EWMA |
| **P2** | **Editor de alertas in-app** (rol Editor, backtest, versionado) | — | construir |
| **P3** | **Constructor de paneles in-app** (modo edición WYSIWYG en la propia página) | `DepartmentLayout`/`Widget`/`WidgetDataSource` + flujo "Promover al panel" de Ask-SLAB (~60%) | modo edición in-context (agregar/mover/redimensionar/editar widget + preview); banner de alcance; 2 renderers nuevos |
| **P4** | **Autoría de exámenes** (admin endurecido) | `config_schema` + inline `TemplateField` (regenera JSON); motor de fórmulas; bandas de referencia | formularios endurecidos; objetivos libres |
| **P5** | **Config de cómputo** (ACWR, techos de carga) | nada — son literales de Python | modelo de config + pantalla admin |
| **P6** | **Motor estadístico Z-score / SD / EWMA** | **nada** (no existe SD/Z/EWMA en el código) | construir (lo comparten CK y HSR) |
| **P7** | **Auditoría + versionado de config** | grupos Editor/Solo-Lectura; `clean()`; `is_locked` | `ConfigChangeLog`; historial/rollback |
| **P8** | **Export de datos** | nada de dato crudo (solo XLSX de gráficos en 2 pantallas) | endpoint XLSX + vista/menú "Datos" |

---

# Parte 1 — Solución por solicitud

## 1. Carga externa (GPS)

### 1.1 Aceleraciones y desaceleraciones — umbrales editables, entrenamiento ≠ partido

**Lo que pide:** umbrales de acc/dec (nº y distancia) editables por el club;
puntos de corte **distintos para entrenamiento vs. partido**; idealmente
normalizar por minuto de exposición (acciones·min⁻¹).

**Estado actual:** los umbrales de acc/dec son literales en dos mecanismos
hardcodeados, ninguno pasa por el motor configurable:
- Techo semanal: `WEEKLY_LOAD_METRICS` (`dashboards/player_state.py:53-61`),
  acc/dec **150–250 n**, sumados en una ventana de 7 días que **mezcla partidos
  y entrenamientos**.
- Alerta de carga: acc/dec a **0.85 × la referencia de partido del jugador**
  (`player_state.py` + `exams/signals.py::check_training_load_alert`).
- Las plantillas GPS (`gps_partido`, `gps_sesion`) **no tienen
  `reference_ranges`**, por eso el motor `AlertRule` no las toca. El evaluador
  **no ve `tipo_sesion`** de un resultado. `dist_acc`/`dist_dec` (la "distancia"
  de acc/dec) se capturan pero **nunca se alertan**.

**Solución propuesta (P1 + P2):**
- Conectar las plantillas GPS al **motor de reglas** (P1): acc/dec pasan de
  literales a `AlertRule` editables (`bound`); `gps_partido` vs `gps_sesion` ya
  separan partido/entrenamiento, y **`scope.session_types`** afina dentro de una
  misma plantilla (p. ej. solo `entrenamiento`).
- Habilitar acc/dec **por distancia** (`dist_acc`/`dist_dec`) como campos alertables.
- **Normalización por minuto = campos calculados** en la plantilla GPS (config, vía
  motor de fórmulas): `acc_dec_min = ([acc]+[dec])/[tot_dur]`, etc. Cualquier regla
  puede apuntarles — **sin código de motor**.
- Todo se ajusta desde el **Editor de alertas in-app** (P2), con backtest.

**Config vs. código:** *código una vez* (conectar GPS + `scope.session_types`);
por-minuto y umbrales = **config**. · **Fase 1.**

### 1.2 Techos de HSR/sprint — dinámicos, individualizados, por banda

**Lo que pide:** techos configurables con ≥3 modos (absoluto editable /
desviación vs. su media móvil ~4 sem como Z-score o % del basal / % de la demanda
de partido); **bandas HSR y sprint independientes**; estratificación por
posición; normalización por minuto (m·min⁻¹); contexto por día de microciclo
(MD-4/-3/-1/MD); y que la alerta **informe cuánto se desvía** de la referencia
individual.

**Estado actual:** HSR (1800–2600 m) y sprint (400–700 m) ya son bandas
**separadas** pero **fijas** (`player_state.py:43-51`). "% de demanda de partido"
ya existe (radar + base de la alerta de carga vía `match_load_refs`, ratio fijo
0.85). "Media por posición" existe como widget (`position_comparison`,
`dashboards/aggregation.py:250`) pero **no alimenta ningún umbral**.
Desviación vs. media móvil existe como el kind `variation` de `AlertRule`
(mean-based, **nunca Z-score** — no hay SD en el código). No hay normalización
m·min⁻¹ de HSR/sprint ni codificación de día de microciclo.

**Solución propuesta (P1 + P6 + P2) — todos los modos, un motor:**
- **Absoluto:** `bound` con **mapa banda-por-línea** (`config.by_role`: p. ej.
  Lateral/Extremo 700, Central/Interior 450, Delantero 550, default 500). Una sola
  regla por métrica.
- **Intraindividual:** nuevo kind **`zscore`** vs. basal móvil (ventana
  configurable, media móvil o **EWMA**) — usa el **motor estadístico P6** (media +
  SD por jugador). **Sin config por línea** (ya compara al jugador consigo mismo).
- **% demanda de partido:** nuevo kind **`pct_match`** con **ratio editable**
  (promueve `match_load_refs`, hoy fijo 0.85). **Sin config por línea** (vs. su
  propia demanda de partido).
- **Bandas independientes:** HSR y sprint son campos separados → reglas separadas.
- **Por línea:** solo aplica al **modo absoluto** (los individualizados ya normalizan
  la posición). Keys off **`Position.role`** (grupo per-club ya existente).
  `scope.roles` disponible en cualquier regla para restringir por línea.
- **Por minuto:** campos calculados `hsr_min`, `sprint_min` (config).
- **Por microciclo (MD):** `scope.microcycle_days`; el `md_label` se **graba en el
  resultado al ingestar** (derivado del fixture), no se recalcula.
- **Reportar la desviación:** el mensaje incluye el valor del desvío
  (z / % del basal / % de la demanda de partido).

**Config vs. código:** *código una vez* (kinds `zscore`/`pct_match`, motor P6, mapa
`by_role`, `md_label` al ingestar); luego **modo + umbral + scope = config**.
· **Fase 1.**

### 1.3 Ratio agudo:crónico (ACWR) — transparente y editable

**Lo que pide:** declarar qué variables y método alimentan el ACWR; permitir
configurar ventanas (7:28 u otras), método (media móvil o **EWMA**) y selección
de variables (distancia total, HSR, carga de acel, sRPE…); calcular ACWR sobre
**varias variables en paralelo**.

**Estado actual:** ACWR real pero **hardcodeado** en `api/roster.py:135`
(`_player_acwr`) y `api/command_center.py:171` — **una sola variable
(`tot_dist`)**, método suma móvil acoplada 7d ÷ (28d/4), consumido por
`dashboards/readiness.py`. Ventanas, el `/4`, la variable y el método son
literales. No existe EWMA en el código. El tooltip muestra km agudo/crónico pero
**no** qué variable ni qué método.

**Solución propuesta (P5 + P6) — ACWR transparente, editable y alertable:**
- Modelo de **config de ACWR** (P5): variable(s) seleccionables, ventanas, método
  (media móvil / **EWMA**), **multi-variable en paralelo** (un valor por variable).
- Centralizar el cómputo (hoy duplicado en `roster.py` + `command_center.py`) para
  que lea la config.
- **Transparencia:** el tooltip/tarjeta declara variable + método + ventanas.
- **Alertable con banda objetivo editable por métrica** (decisión 2026-07-13): cada
  variable de ACWR se expone como campo calculado `acwr_<variable>` sobre el que se
  puede poner una **banda editable** (`bound`/`band`) que dispara alerta al salirse —
  vía el mismo motor.
- Config editable en **Django admin endurecido** (baja frecuencia) + el editor de
  alertas para las bandas.

**Config vs. código:** *código una vez* (modelo de config, EWMA, multi-variable,
centralizar, exponer `acwr_<var>` como campo alertable); luego
**variables/ventanas/método/banda = config**. · **Fase 1** (movido desde Fase 2 por
"todo junto").

### 1.4 Alertas de GPS fuera de contexto *(crítico)*

**Lo que pide:** caducidad temporal — **suprimir automáticamente si no hay sesión
en las últimas 72 h**; toda alerta debe **mostrar la fecha del dato** que la
origina; distinguir explícitamente **alerta activa vs. histórica**.

**Estado actual:** §3.57 (2026-07-05/06) ya trajo parte: la fecha del dato va
*embebida como texto* en el `message`, y hay barridos de caducidad (30 d
carga/umbral, 7 d check-in, guarda de 10 d en la alerta de carga). Pero: **no hay
campo estructurado** de fecha del dato en `Alert`; **no hay compuerta de 72 h**;
el front solo consulta `status=active` y **no distingue activa/histórica**. Y el
bug raíz: `compute_weekly_load` ancla su ventana al **último registro GPS**, no a
hoy (`player_state.py:80`) → tras 5 días libres sigue marcando "sobre el techo".

**Solución propuesta (Fase 0 — código; expiry editable → Fase 1):**
- **Bug raíz:** anclar la ventana a **hoy** + recompute diario + compuerta de
  reciente-exposición en los consumidores (Centro de mando / Daily).
- **Fecha estructurada:** `Alert.source_recorded_at` (migración), seteada al
  disparar en los 3 generadores; expuesta en el schema y renderizada como chip
  "dato del 4-jul".
- **Compuerta de 72 h:** no disparar (y barrer) alertas GPS/carga si no hay
  `gps_sesion`/`gps_partido` en las últimas 72 h. (Constante ahora; **perilla
  editable en Fase 1** vía P1.)
- **Activa/histórica:** badge de frescura sobre activas + vista **Historial**
  (`status=resolved` ya existe).

**Config vs. código:** *código* (bug, campo, compuerta, UI); la **ventana de
caducidad** se vuelve config en Fase 1. · **Fase 0** (el corazón del pedido
"crítico").

---

## 2. Check-in / Wellness — adherencia

**Lo que pide:** vista explícita de adherencia — tabla filtrable por fecha con
los jugadores que **no respondieron** ese día; **% de cumplimiento** por jugador
y por plantel en el período; la adherencia como dato de calidad de la medición.

**Estado actual:** **no existe** ninguna vista de adherencia/no-respondedores
(el asistente de IA describió una capacidad que la plataforma no tiene). Solo hay
conteos: `wellness_hoy = {n, expected}` en el Daily (`api/daily_report.py:163`,
solo número, no *quién*) y un KPI de completitud en el Centro de mando que además
**cuenta el slug muerto `check_in`** en vez del vivo `checkin_fisico`
(`api/command_center.py:274`). El material ya está: roster activo + resultados
`checkin_fisico` por fecha.

**Solución propuesta (P3 + consulta pura):** mostrar los no-respondedores del día
en las **dos superficies de arranque** — así el usuario ve *desde que entra*
quién no completó el check-in, sin tener que navegar a buscarlo.
- **Centro de mando (home / redirect post-login):** tarjeta de adherencia del día
  — `respondieron/esperados` + % + lista de **quién no respondió**, cada jugador
  con **deep-link a su ficha** (consistente con 7.2). Enriquecer el builder
  `build_command_center` (`api/command_center.py`) con un bloque
  `checkin_adherence: {responded, expected, pct, no_respondieron:[{player_id,
  name, position}]}`.
- **Daily (vista de reunión 8 AM):** bloque "No respondieron el check-in hoy"
  junto al KPI strip — extender `wellness_hoy` con `no_respondieron[]`.
- **Endpoint de período** `GET /api/wellness-adherence?category_id=&date_from=&date_to=`:
  grilla por jugador/día + `respuestas/esperados → pct` + roll-up de plantel.
- **Widget de reporte** `team_checkin_adherence` (P3) para el % por
  jugador/plantel en la ventana elegida (reusa `DateRangeControl` + export).
- **Consolidar en un solo template de wellness.** `checkin_fisico` es el
  **canónico** (17 referencias, el feed vivo del Google Form). Apuntar el KPI de
  completitud a él (`command_center.py:274` hoy consulta el slug **muerto**
  `check_in` → el KPI queda ciego al feed real) y **retirar el `check_in`
  legacy** repuntando los stragglers (`seed_demo_layouts`, `seed_fake_exams`,
  `seed_check_in`) y archivando/borrando la plantilla con guarda. **No** renombrar
  `checkin_fisico → check_in`: invertiría la migración §3.57, toca ~24 sitios,
  choca con el slug existente y arriesga el feed vivo — por una ganancia
  cosmética.

**Config vs. código:** *código* (consulta + endpoint + widget), **sin migración**.
· **Fase 0.**

> **Alcance (aclarado por el club, 2026-07-12):** es **solo informativo** — no
> dispara ninguna alerta. El objetivo es que el staff vea quién no respondió y
> **lo llame**; por eso cada no-respondedor va con deep-link a su ficha para
> actuar al toque.
>
> Esto **cierra la decisión del denominador**: en las vistas de *hoy* (Centro de
> mando + Daily) basta la **lista** (esperados = roster activo; no hay % que
> calcular). Para el widget de período usamos un denominador **auto-calibrado** =
> *días con actividad de check-in en la categoría* (proxy de "día en que se
> esperaba respuesta"), así los días de descanso no distorsionan y **no**
> dependemos del calendario de entrenamientos. Se mantiene el chip visual de
> "lesionado" para que su ausencia se lea distinto.

---

## 3. Módulo de lesionados

### 3.1 Clasificación Fuller + fecha «disponible para ser citado»

**Lo que pide:** los estados actuales (Lesionado → En recuperación → RTT → RTP)
son conceptualmente inconsistentes. Estados propuestos: Lesionado–fase aguda /
Lesionado–fase intermedia / Reintegro / Reintegro+entrenamiento parcial / RTT /
RTP. **Clave:** un campo **independiente** para la fecha en que el jugador queda
«disponible para ser citado» — es el que **cierra el conteo de días de baja
(Fuller)** y **no coincide** necesariamente con un cambio de estado; registrable
en cualquier punto, en paralelo.

**Estado actual:** el **formato** Fuller ya aterrizó (§3.56: 18 regiones + `lado`,
mecanismo, severidad de 5 pasos, importador `import_lesiones`). Pero la **máquina
de estados** es la que él objeta: un único campo categórico `stage`
(`seed_lesiones.py:151`, valores injured/recovery/reintegration/closed) maneja
`Player.status` vía un mapa hardcodeado (`core/models.py:171-187` +
`episode_lifecycle.py`). El conteo de baja solo se cierra al **cerrar el episodio
= RTP** (`actual_return_date`/`Episode.ended_at`). **No existe** ningún campo de
"disponible/citable" independiente.

**Solución propuesta (P4 + esquema):**
- **Estados — resuelto (2026-07-12), Opción A + mapa configurable:** las 6 fases
  clínicas se agregan como opciones del campo `stage` (config). El mapeo
  fase → `Player.status` deja de estar hardcodeado (`_map_stage_to_player_status`)
  y pasa a **config editable en Django Admin** sobre `episode_config` (implementa el
  `severity_level` previsto en STATUS.md:997-1001), para que el médico ajuste el
  bucket de disponibilidad **sin tocar código**. **Sin migración del enum
  `Player.status`** (se mantienen los 4 buckets). Mapeo por defecto (editable):
  aguda→`injured`, intermedia→`recovery`, reintegro→`reintegration`,
  reintegro+parcial→`reintegration`, RTT→`reintegration`, RTP→`available` (cierra el
  episodio). La **fase fina** se muestra además como **etiqueta secundaria**
  app-wide (roster, Daily) leída del `stage` del episodio abierto, sin ser un valor
  de `Player.status`.
- **Fecha «disponible para ser citado» (el corazón del pedido):** nueva columna
  `Episode.available_at` (migración) + ruta de escritura (extender
  `PATCH /episodes/{id}` — hoy solo permite `status=closed`) + serializer + UI.
  Al vivir en el `Episode` es **ortogonal** al `stage`: se marca en cualquier
  momento sin cambiar de estado.
- **Re-anclar el conteo de baja** (Fuller time-loss) a `available_at`, con
  fallback a `ended_at` (`daily_report._lesionado`, PDFs de lesiones).

**Config vs. código:** estados = **config**; fecha citable + re-anclaje =
**código/esquema**. · **Fase 3.**

### 3.2 Fecha estimada vs. real de retorno

**Lo que pide:** definir en la interfaz *estimada = pronóstico al diagnóstico* /
*real = disponibilidad efectiva*; **versionar la fecha estimada** (auditar la
precisión del pronóstico); reportar automáticamente la **desviación
pronóstico–real** como indicador de gestión.

**Estado actual:** `expected_return_date` y `actual_return_date` existen como
campos de fecha (`seed_lesiones.py:168,172`) sin guía en UI. **El historial de
pronósticos ya está físicamente almacenado**: cada actualización de etapa es un
`ExamResult` nuevo que congela su `expected_return_date` con su `recorded_at`
(consultable vía `GET /episodes/{id}/results`). El motor de fórmulas **no** puede
calcular la desviación (es numérico, de un solo resultado, sin fechas).

**Solución propuesta — pronóstico vs. real, auditable:**
- **Definiciones en UI (config, P4):** `help_text` en los campos — **estimada =
  pronóstico de disponibilidad al diagnóstico**; **real = disponibilidad efectiva =
  `Episode.available_at`** (el marcador Fuller de §3.1). Así estimado y real miden lo
  mismo (disponibilidad/citable) y son comparables. (Opcional: comparar también
  contra RTP `actual_return_date` como métrica secundaria.)
- **Versionado (sin esquema nuevo):** el rastro **ya existe** físicamente — cada
  actualización de etapa es un `ExamResult` que congela su `expected_return_date`
  con su `recorded_at`. Construir una lectura **"historial de pronóstico"**
  (`GET /episodes/{id}/results` → serie de estimaciones) + **arreglar el prefill**:
  hoy `InjuryPanel` copia el pronóstico anterior en silencio → pasa a mostrarlo
  **read-only con acción explícita "actualizar pronóstico"**, para que cada
  re-pronóstico sea deliberado y quede registrado.
- **KPI de desviación (código de lectura, sin migración):**
  - por episodio: `error_dias = available_at − primer expected_return_date` (con
    signo: + tardó más de lo previsto, − volvió antes).
  - por departamento/período: **sesgo** (media con signo → sub/sobre-estimación
    sistemática) + **MAE** (precisión) — el indicador de calidad de gestión médica.
  - **trayectoria del pronóstico** (cómo evolucionaron las estimaciones) en el
    detalle del episodio.
- Se muestra como **widget de reporte Médico**, colocable/config vía el Constructor
  de paneles (P3). El motor de fórmulas **no** sirve acá (numérico, de un solo
  resultado, sin fechas) → es una agregación backend nueva.

**Config vs. código:** definiciones = config; historial + KPI + fix de prefill =
**código de lectura** (sin esquema nuevo — los insumos ya existen; `available_at`
viene de §3.1). · **Fase 3.**

---

## 4. Creatina Quinasa (CK) — semáforo por desviación individual

**Lo que pide:** la CK tiene altísima variabilidad intraindividual → el valor
absoluto y la comparación entre jugadores no sirven. Visualización pedida: filtro
por fecha; **gráfico de barras, una barra por jugador** con la CK del día;
**color de la barra por la desviación respecto del basal individual (Z-score o
CV)** en semáforo (verde/amarillo/rojo); umbrales del semáforo **editables por el
club**.

**Estado actual:** exactamente lo que él critica — la CK se muestra hoy como
leaderboard de **valores absolutos** con líneas de referencia fijas (200/500) y
promedio de plantel (`seed_demo_layouts.py:419-448`), más un uso de `[ck.valor]`
en fórmulas cross-template (la "correlación" que objeta). **No existe cómputo de
media/SD/Z/CV intraindividual** en ninguna parte, y las barras del leaderboard
son de **color uniforme** (no hay color por-barra derivado de un estadístico).

**Solución propuesta (P6 + P3 + P1) — el leaderboard, recoloreado:**
- **La variación es lo primero, no el valor.** El club quiere ver el
  **comportamiento del dato**, no el número absoluto (coincide con el fundamento del
  médico: la CK absoluta no es interpretable). Por eso, en el **`TEAM_LEADERBOARD`**
  extendido, por defecto la **altura de la barra = la desviación** (Z-score o CV, con
  signo) vs. su basal móvil, y el **color** = semáforo por esa misma desviación
  (`stats.py`, P6 — el mismo de §1.2). El **valor crudo de CK** va en la
  etiqueta/tooltip. Ordenable por desviación (los que más se salen, arriba). Toggle
  de config `height: deviation | value` por si alguna vez quieren la altura = valor
  (el pedido literal del PDF).
- **Filtro por fecha:** ya existe (ventana de un día en el reporte de equipo).
- **Estadístico + ventana basal + umbrales del semáforo = config del widget**,
  editables en el **Constructor de paneles** (P3): el club elige Z-score o CV, la
  ventana, y los cortes (p. ej. |Z|<1.5 verde / 1.5–2.5 amarillo / >2.5 rojo). Las
  líneas absolutas 200/500 quedan **off por defecto** (el color lleva el significado).
- **Alerta opcional de CK** (decisión 2026-07-13): además del color, una regla
  **`zscore` sobre `ck.valor`** en el motor (Fase 1) avisa en la campana cuando el
  jugador se sale de su banda. El color es lo visual; la alerta, el aviso proactivo.
- **CK por jugador (perfil) = la vista de "comportamiento en el tiempo"** (decisión
  2026-07-13): la línea de CK overlaya su **media móvil ± SD** como banda sombreada
  (reusa `stats.py`); se lee cómo se **mueve** el dato respecto de su propio normal,
  no el valor suelto — consistente con el mapeo de §7.2.

**Config vs. código:** *código una vez* (extender leaderboard + color por-barra;
banda basal en la línea del perfil); estadístico/ventana/umbrales = **config**.
El motor `stats.py` y el kind `zscore` ya vienen de Fase 1. · **Fase 2** (reusa P6).

---

## 5. Exportación de datos *(máxima prioridad)*

**Lo que pide:** botón de descarga **CSV en todos los módulos, sin excepción**;
filtrable por rango de fechas, jugador, posición, tipo de prueba, tipo de
evaluación y **tipo de sesión (entrenamiento/partido)**. "El dato pertenece al
club".

**Estado actual:** **no existe exportación de dato crudo** en el backend. El
`openpyxl` es solo para *ingesta*. El "Descargar Excel" es client-side, XLSX, en
**2 pantallas**, y transcribe **los widgets renderizados, no las filas**. No se
puede sacar el `ExamResult` subyacente.

**Solución propuesta (P8) — vista + ítem de menú "Exportar datos":** una **vista
dedicada** (no botones sueltos) desde donde el usuario arma la exportación.
- **Ubicación en el menú:** nuevo grupo **"Datos"** (expandible, sección Análisis),
  el hogar de datos del sidebar: **"Subir datos"** (§7.1, rol Editor),
  **"Exportar datos"** (rol Editor) y **"Uso"** (visible **solo superuser** — se mueve
  aquí el ítem actual que hoy vive suelto en Administración).
- **La vista Exportar:** elegir **jugadores** + **exámenes agrupados/ordenados por
  departamento** + rango de fechas (opcional posición / tipo de sesión). El listado
  de exámenes por departamento **reusa el endpoint category-scoped que también
  alimenta el "Subir datos" de §7.1** (`GET /api/templates?category_id=&department=`)
  — se construye una vez.
- **Formato de salida = Excel (XLSX):** cada **fila = (jugador, fecha)** con
  **todos los valores del examen, incluidos los calculados**. **Una hoja por
  examen** (ordenadas por departamento), porque las columnas difieren por examen.
  Generado **server-side** con `openpyxl` (ya es dependencia — hoy solo para
  ingesta; ahora también para salida).
- **Endpoint** `GET /api/export/results.xlsx`: `category_id`, `player_ids`,
  `template_ids` (los exámenes elegidos), `date_from`/`date_to` (reusa
  `_parse_date_window`), opcional `position_id` / `event_type` (tipo de sesión =
  split GPS `gps_partido`/`gps_sesion` + `event.event_type`).
- **Headers** desde `config_schema['fields']` (promover `_catalog_fields` de
  `assistant_tools.py` a util compartida); calculados salen como columnas;
  categóricos humanizados vía `option_labels`; unidad en el encabezado.
- **Scoping** `scope_results`/`scope_templates`/`scope_players` + `require_perm`
  (gate **Editor**).

**Config vs. código:** *código* (es una feature). Encaja de lleno en la filosofía
self-service: el club saca su propio dato cuando quiera. · **Fase 0** (la #1).

> **Decisiones (cerradas):** **XLSX ancho, fila = jugador-fecha, una hoja por
> examen** (calculados incluidos; CSV opcional si se pide más adelante). **Menú:**
> grupo **"Datos"** = **"Subir datos"** (§7.1) + **"Exportar datos"** (rol Editor) +
> **"Uso"** (solo superuser).

---

## 6. Motor de gráficos con IA (Ask-SLAB)

**Lo que pide:** el generador de gráficos con IA rinde por debajo de lo que se
obtiene procesando los mismos datos afuera; revisar y elevar el estándar. Él mismo
dice que esto **refuerza el punto 5** (export).

**Estado actual:** el asistente (`dashboards/assistant.py`) usa un modelo
**viejo** — `claude-opus-4-7` (`config/settings.py:23` + `.env`, hardcodeado como
fallback en ~8 lugares). El LLM **nunca ve filas crudas**: recibe salidas
pre-agregadas y emite un *spec* de gráfico de un catálogo fijo (8 team / 5
player), resuelto por un agregador determinista. Los ratios/derivados están
**explícitamente rechazados** por el prompt. Techo estructural.

**Solución propuesta:**
- **Ganancia inmediata:** subir el modelo (`claude-opus-4-7` → modelo actual;
  el env var **y** los ~8 fallbacks); ampliar el vocabulario (scatter, box-plot,
  correlación); habilitar un path de campo calculado/ratio.
- **El techo real:** el LLM no toca dato crudo → **el export (P8/#5) es la
  verdadera respuesta**. Se scopean juntos: el export da análisis sin
  restricciones *ya*, y desdramatiza el #6.

**Config vs. código:** *código* (bump + vocabulario). · **Fase 4** (el bump del
modelo es barato y puede adelantarse).

> 🔴 **Seguridad:** aparece un `ANTHROPIC_API_KEY` vivo commiteado en
> `backend/.env`. Rotar + sacar del repo, independiente de este trabajo.

---

## 7. Usabilidad e interfaz

### 7.1 Botones de registro rápido en vistas centrales

**Lo que pide:** accesos de registro rápido en las ventanas centrales, no solo en
vistas secundarias.

**Estado actual:** el quick-add solo vive en el perfil (`DepartmentCard`:
"+ Agregar" / "Capturar todos"). En las centrales: el "Acciones rápidas" del
Centro de mando son 3 **links genéricos** a `/equipo` y `/reportes/fisico` (stub,
no un registro real); Equipo solo tiene "Agregar jugador" (admin de roster).

**Solución propuesta — lanzador "Subir datos" en la barra lateral (P4 + P3):**
un menú **persistente** en el sidebar con la estructura **Subir datos →
Departamento → Exam Template**, para iniciar la captura desde cualquier pantalla
sin navegar a buscarla.
- **Menú anidado:** reusa el patrón de grupo expandible que el sidebar **ya
  tiene** (hoy "Dashboard → [departamentos]", `Sidebar.tsx`), extendido un nivel
  más (departamento → plantillas). Departamentos y plantillas se **escopean a la
  categoría seleccionada** (CategoryProvider, principio IA #5).
- **Sin cambiar de página:** al elegir una plantilla se abre la captura en un
  **`<Modal>`** sobre la pantalla actual (principio IA #8), despachando por el
  `input_config.default_input_mode` del template:
  - `team_table` → grilla de plantel (`TeamTableForm`, no requiere elegir jugador).
  - `single` → `DynamicUploader` con selector de jugador arriba.
  - `bulk_ingest` → `BulkIngestForm` (dropzone de archivo).
  Reusa los componentes de formulario que ya existen — solo cambia el host
  (modal en vez de la página `registrar`).
- **Backend:** nuevo `GET /api/templates?category_id=&department=` (o
  `capture-menu`) que lista plantillas por departamento, escopeado por membresía
  (hoy solo existe el listado **por jugador** `/players/{id}/templates`). El resto
  (`POST /results`, `/results/team`, `/results/bulk`) ya existe.
- **Gobernanza:** el menú aparece solo para el rol **Editor**
  (`require_perm("exams.add_examresult")`), consistente con la decisión de
  gobernanza.
- **Simetría con §5:** es el espejo del lanzador **"Exportar datos"** (mismo árbol
  Departamento → Template). **"Subir datos" vive bajo el mismo grupo "Datos"** de §5
  (Datos = Subir datos + Exportar datos + Uso) — un único hogar de datos en el
  sidebar.

Mantiene los accesos por-jugador existentes (`DepartmentCard` "+ Agregar" /
"Capturar todos"); esto es un punto de entrada **global** adicional.
· **Fase 4** (frontend-pesado; puede adelantarse a Fase 0 junto con "Exportar
datos" si se quiere el par upload/download de una).

### 7.2 Deep-link de "hacer la tarea" al jugador que la originó

**Lo que pide:** el botón "hacer la tarea" debe enlazar directamente a la ficha
del jugador específico, no a una vista común.

**Estado actual:** el dead-end es preciso — las tarjetas de sugerencia del
**Briefing/Ask-SLAB** calculan la CTA como `/reportes/{dept}` (genérico), y los
items cargan a los jugadores como **nombres, no IDs** (`dashboards/briefing.py:213`
emite `str(p)`). La campana del navbar ya deep-linkea bien; `DecisionTable`/
`SquadStatus` llegan al jugador pero al root del perfil (sin tab).

**Solución propuesta — rediseño de la tarjeta de sugerencia** (evoluciona el
pedido literal, decisión del equipo 2026-07-12): en vez de un solo botón "hacer la
tarea" que caía en una vista genérica, cada tarjeta se vuelve una mini-unidad
accionable:

- **Mensaje de alerta** (el `title` del item) — qué pasó.
- **Detalle** con **números y fechas concretos** (p. ej. *"CK 720 U/L el
  2026-07-10, +2.3σ sobre su basal, 3 sesiones consecutivas"*). Se arma de
  `evidence[]` + `recommendation`; para que los números **no** sean prosa del LLM,
  el backend **enriquece** el detalle con el valor+fecha **reales** de la última
  lectura de la métrica (`PlayerMetricState`).
- **Dos botones:**
  1. **"Ver info"** → `<Modal>` con **el gráfico de la métrica** que originó la
     sugerencia (para ese jugador) + un texto que **explica la alerta y la CTA**.
     **El tipo de gráfico se DERIVA del tipo de alerta, no lo elige el LLM** (más
     confiable y consistente; además esquiva el problema de §6). Regla:
     - `variation`/`zscore`/`ewma`/% demanda de partido (tendencia/desviación) →
       **línea temporal** + basal/referencia, con el punto de disparo marcado.
     - `bound` (límite fijo) → **línea temporal** + línea(s) de límite horizontal.
     - `band` (rangos clínicos, p. ej. CK/wellness) → **línea temporal** + zonas
       sombreadas.
     - `goal` con métrica → **línea** hacia el target + marca de `due_date`.
     - molestia / medicación (WADA) / categórico (cualitativo) → **tabla** de
       lecturas recientes + nota.

     Es decir: casi todo es **una misma línea temporal**; solo cambia el *overlay*
     (basal / límite / zonas / target). Preferimos la línea incluso para límite y
     banda porque muestra la **tendencia** (¿spike puntual o problema sostenido?) —
     justo lo que hace la alerta auditable. El **bar/gauge** es para comparación
     entre jugadores (la vista de equipo de §4), no para este modal. Reusa
     `resolve_player_chart_spec` (transitoria).
  2. **"Agregar a plan de trabajo"** → `<Modal>` que muestra el **plan de trabajo
     actual del jugador** (`GET /players/{id}/daily-notes?kind=plan`) + la **nueva
     tarea pre-cargada** desde la recomendación, lista para agregar con **un clic**
     (`POST /daily-notes` con `kind="plan"`). Gate `require_perm(core.add_dailynote)`
     (rol Editor).

**Prerrequisito compartido:** el item debe portar `player_ids` (hoy solo lleva
nombres, `briefing.py:213`) — la misma resolución nombres→IDs que habilita los
deep-links de adherencia (§2) y la campana. Con eso ambos botones saben a qué
jugador y a qué métrica apuntan.

- **Backend:** `briefing.py` agrega `player_ids` + la **referencia de métrica**
  `{template_slug, field_key}` por item (**el `chart_type` NO lo elige el agente —
  se deriva del tipo de alerta**; si la tarjeta está atada a una alerta real, el
  kind + la métrica se leen directo de la alerta). Enriquece números/fechas reales
  desde la lectura / `PlayerMetricState`. **El LLM conserva solo la recomendación /
  CTA + prioridad.** Fallback: sin métrica → el modal muestra solo la explicación
  (sin gráfico). Reusa `daily-notes` (`GET /players/{id}/daily-notes?kind=plan` +
  `POST /daily-notes`, `kind` `pauta`/`plan`) y la resolución de charts.
- **Frontend:** rediseñar la tarjeta en `BriefingPanel.tsx` (mensaje + detalle +
  2 botones) + `BriefingInfoModal` (gráfico + explicación) + `AddToPlanModal`
  (plan actual + tarea pre-cargada, agregar con un clic). Todos con `<Modal>`.
  Añadir `?tab=` a los links de `DecisionTable`/`SquadStatus`.

> **Nota:** esto **reemplaza** la antigua "decisión menor" (tab vs. formulario):
> el botón único "hacer la tarea" se sustituye por **"Ver info"** (contexto) +
> **"Agregar a plan"** (acción). El deep-link a la ficha queda como enlace
> secundario dentro de "Ver info" si se quiere.
>
> **Resuelto (2026-07-13):** el **gráfico se deriva del tipo de alerta** (línea
> temporal + overlay según kind; tabla para cualitativo) — el LLM **no** elige
> gráfico ni recita números. **Números = backend-enriquecidos** desde la lectura
> real. El LLM conserva la **recomendación / CTA** y la prioridad. Este mismo patrón
> arregla §6: **LLM para las palabras, motor determinista para la imagen y las
> cifras.**

· **Fase 0** (crece de alcance: rediseño de tarjeta + 2 modales; el prerrequisito
`player_ids` es compartido con §2).

### 7.3 Lista de objetivos editable

**Lo que pide:** permitir agregar y quitar objetivos de la lista.

**Estado actual:** el CRUD de objetivos por jugador **ya está cableado**
(`ProfileGoals`: crear vía `POST /goals`, cancelar vía `PATCH`, borrar vía
`DELETE`). Lo único "fijo" es que un objetivo debe **mapear a un campo numérico**
de una plantilla existente — no hay objetivo libre/cualitativo. (Candidatos
secundarios: el `Metas` legacy con dropdowns fijos, deprecado; el widget
`goals_list` reservado sin renderer.)

**Solución propuesta — objetivos de dos tipos** (aclarado por el equipo
2026-07-12): un objetivo puede estar **ligado a una métrica** o **no**; si no lo
está, es **texto + fecha**.
- **Objetivo con métrica** (comportamiento actual): template + `field_key`
  numérico + operador + `target_value` + `due_date`; el evaluador lo transiciona
  automáticamente a `met`/`missed` contra la última lectura.
- **Objetivo libre (texto):** un `title`/texto + `due_date`, **sin** métrica.
  **No** se auto-evalúa. Se cierra **manualmente** con dos acciones — **"Marcar
  cumplido"** (`met`) o **"Marcar no cumplido"** (`missed`) — o cancelar. Al llegar
  la `due_date` sin cerrar **NO** pasa a `missed` solo: en su lugar dispara una
  **alerta persistente en la campana del navbar** ("Objetivo vencido — pendiente
  de cierre") que **se mantiene hasta que el usuario lo marca cumplido / no
  cumplido / cancela**.

- **Modelo (`goals/models.py::Goal`):** hoy `template`, `field_key`, `operator` y
  `target_value` son **obligatorios**. Cambio: hacerlos **nullable/blank** +
  agregar `title` (el texto del objetivo). El tipo se infiere de si hay métrica
  (o un `kind` explícito `metric`/`text`). Migración. Nuevo
  **`AlertSource.GOAL_OVERDUE`**.
- **Evaluador (`goals/evaluator.py`):** en el tick diario, los goals con métrica se
  transicionan como hoy; los **libres NO** se auto-transicionan — si están vencidos
  y sin cerrar, se dispara/refresca la alerta persistente **`GOAL_OVERDUE`**. Se
  **auto-descarta** al cerrar el objetivo (met/missed/cancelado), igual que el
  `goal_warning`, y queda **exenta del barrido de caducidad de 30 días** (la familia
  goal ya está exenta — vive por ciclo de fecha). También se saltean en
  `sync_evaluate_for_result` (no tienen lectura).
- **Campana del navbar:** ya lista alertas activas y deep-linkea a
  `?tab=objetivos`, así que la alerta aparece ahí sin trabajo extra.
- **API:** `POST /goals` ramifica la validación (con métrica → como hoy; libre →
  `title` + `due_date`); `PATCH /goals/{id}` permite el cierre **manual** de
  objetivos libres a `met` **o** `missed` (+ `cancelled`) — hoy `met`/`missed` son
  solo del evaluador — y al cerrar descarta la alerta `GOAL_OVERDUE`.
- **Frontend (`ProfileGoals`/`GoalForm`):** toggle "Con métrica / Libre (texto)";
  las tarjetas libres muestran texto + fecha + estado + **"Marcar cumplido" /
  "Marcar no cumplido" / "Cancelar"**.

Esto **completa** el pedido "lista de objetivos editable": deja de estar limitada
a campos numéricos. · **Fase 3.**

---

# Parte 2 — Todos los cambios (backlog de trabajo)

> Checklist por fase. Cada fase es entregable de forma independiente.
> Solicitudes que resuelve entre `()`.

## Fase 0 — Confianza + fundaciones

**Bug de carga fuera de contexto (1.4)**
- [ ] `dashboards/player_state.py:80` — anclar la ventana de `compute_weekly_load`
      a `timezone.now()`; actualizar docstring.
- [ ] `config/celery.py` — beat diario ~05:00 `rebuild_player_state`.
- [ ] `api/command_center.py` + `api/daily_report.py` — compuerta de
      reciente-exposición sobre el veredicto "over ceiling" (ignorar si el último
      GPS es más viejo que la ventana).

**Fecha estructurada + 72 h + activa/histórica (1.4)**
- [ ] `goals/models.py::Alert` — campo `source_recorded_at` (DateTime, null) +
      migración.
- [ ] `goals/evaluator.py::_upsert_alert` — setear `source_recorded_at` al crear
      y refrescar; rama GPS **72 h** en `expire_stale_alerts`.
- [ ] `exams/signals.py::check_training_load_alert` — guarda de disparo 72 h +
      `source_recorded_at`.
- [ ] Señal de medicación + `reevaluate_medication_alerts` — `source_recorded_at`.
- [ ] `api/schemas.py::AlertSchema` — exponer `source_recorded_at`.
- [ ] Front: `ProfileAlerts/AlertList`, `dashboards/widgets/PlayerAlerts`,
      `reports/widgets/TeamAlerts` — chip "dato del …" + badge activa/histórica +
      vista Historial (`status=resolved`).

**Exportar (vista + menú) (5)**
- [ ] `api/export.py` (nuevo) — `GET /api/export/results.xlsx` (server-side
      `openpyxl`): params `category_id`, `player_ids`, `template_ids`,
      `date_from`/`to`, opcional `position_id`/`event_type`; scoping +
      `require_perm` Editor. Workbook: **una hoja por examen** (ordenadas por
      depto), fila = (jugador, fecha), columnas = valores + calculados.
- [ ] Promover `_catalog_fields`/`_schema_fields` de `dashboards/assistant_tools.py`
      a util compartida (headers + unidades + labels de categóricos).
- [ ] Reusar `GET /api/templates?category_id=&department=` (compartido con §7.1)
      para el picker de exámenes por departamento.
- [ ] Front: vista **`/exportar`** (pickers de jugadores + exámenes por depto +
      rango de fechas → descarga XLSX).
- [ ] Nav (`Sidebar.tsx`): nuevo grupo **"Datos"** con **"Exportar datos"** (rol
      Editor) y **"Uso"** (solo superuser — mover el ítem actual bajo "Datos").
      ("Subir datos" se suma al mismo grupo en Fase 4, §7.1.)

**Rediseño de tarjetas de sugerencia + plan de trabajo (7.2)**
- [ ] `dashboards/briefing.py` — resolver nombres → `player_ids`; emitir la
      **referencia de métrica** `{template_slug, field_key}` (el `chart_type` **se
      deriva del tipo de alerta**, no lo elige el agente; si hay alerta real, kind +
      métrica salen de la alerta); enriquecer el detalle con valor+fecha reales
      (`PlayerMetricState` / última lectura); actualizar el schema.
- [ ] Front: rediseñar la tarjeta en `components/command/BriefingPanel.tsx` +
      `types.ts` — mensaje de alerta + detalle (números/fechas) + 2 botones.
- [ ] `BriefingInfoModal` — gráfico **derivado del tipo de alerta** (línea temporal
      + overlay: basal/límite/zonas/target; **tabla** si es cualitativo), reusa
      `resolve_player_chart_spec` + texto que explica alerta y CTA.
- [ ] `AddToPlanModal` — plan actual (`GET /players/{id}/daily-notes?kind=plan`) +
      tarea pre-cargada desde la recomendación, agregar con un clic
      (`POST /daily-notes` `kind=plan`, gate Editor).
- [ ] `DecisionTable`/`SquadStatus`: enlaces con `?tab=` (deep-link consistente).

**Adherencia de wellness (2)**
- [ ] `api/command_center.py::build_command_center` — bloque `checkin_adherence`
      (`responded`, `expected`, `pct`, `no_respondieron:[{player_id,name,position}]`).
- [ ] `api/daily_report.py::_kpis` — `wellness_hoy.no_respondieron[]`.
- [ ] `api/wellness.py` — `GET /api/wellness-adherence` (grilla + % jugador/plantel).
- [ ] Front (Centro de mando): tarjeta `components/command/CheckinAdherenceCard.tsx`
      en `centro-de-mando/page.tsx` — lista con deep-link por jugador.
- [ ] Front (Daily): bloque "No respondieron el check-in hoy" en `/daily`.
- [ ] Front (reporte): widget `team_checkin_adherence` en `reports/widgets/`
      (registrar en `index.tsx`) — denominador auto-calibrado (días con actividad
      de check-in en la categoría); chip "lesionado" en la lista.
- [ ] **Solo informativo, sin alerta** — no crear `AlertRule` de no-respuesta.

**Retiro de `check_in` legacy — un solo template de wellness (2)**
> `checkin_fisico` queda como slug **canónico** (17 refs, el feed vivo). **No**
> renombrar a `check_in`: invertiría la migración §3.57, toca ~24 sitios, choca
> con el slug existente y arriesga el feed vivo, por una ganancia cosmética.
- [ ] `api/command_center.py:274` — apuntar el KPI de completitud a
      `slug="checkin_fisico"` + `applicable_categories=category` (hoy consulta el
      slug muerto `check_in` → ciego al feed real).
- [ ] Repuntar stragglers al canónico: `dashboards/management/commands/seed_demo_layouts.py`;
      decidir sobre `exams/management/commands/seed_fake_exams.py`; retirar el
      comando `exams/management/commands/seed_check_in.py`.
- [ ] Auditar la plantilla `check_in`: ¿tiene `ExamResult`/FKs? → **archivar**
      (desactivar) o **borrar**, solo tras confirmar que no hay datos/referencias.

**Fundación de config (P7) — opcional / puede ir al inicio de Fase 1**
- [ ] Modelo `ConfigChangeLog` (actor, at, target_type, target_id, action,
      before, after) + helper `record_config_change`.
- [ ] Cablear el helper en los paths que mutan config (admin `AlertRule`,
      endpoints de promover widget).
- [ ] Confirmar gating Editor de los modelos de config (`seed_role_groups`).

## Fase 1 — Motor de alertas configurable + Editor in-app (P1, P2) — §1 completo

- [ ] `goals/models.py::AlertRule` — nuevos kinds **`zscore`** y **`pct_match`**;
      opción `method: moving_avg|ewma` en `variation`/`zscore`; **`scope` JSON**
      `{session_types, roles, microcycle_days}`; **`config.by_role`** (mapa
      banda-por-línea) para el kind `bound`. Migración.
- [ ] Conectar plantillas GPS al motor (permitir reglas sobre campos GPS sin
      `reference_ranges` para kinds no-`band`).
- [ ] Módulo estadístico **P6** `stats.py` (rolling mean/SD/Z/CV, EWMA) —
      **compartido con CK (§4)**.
- [ ] Evaluador: filtrar el resultado por `scope` (session_type / rol / MD);
      resolver `by_role` vía `player.position.role`; exponer el desvío
      (z / %basal / %partido) en el mensaje.
- [ ] Campos calculados por-minuto en las plantillas GPS (`hsr_min`, `sprint_min`,
      `acc_dec_min`) — config vía motor de fórmulas.
- [ ] **`md_label` grabado en el resultado GPS al ingestar** (derivado del fixture);
      `scope.microcycle_days` lo consume.
- [ ] **ACWR (§1.3):** modelo de config (variables / ventanas / método MA·EWMA /
      multi-variable); centralizar `_player_acwr` (hoy en `roster.py` +
      `command_center.py`); transparencia en tooltip; exponer `acwr_<var>` como campo
      alertable con **banda objetivo editable**.
- [ ] Ventanas de caducidad **editables** (mover la constante 72 h a config).
- [ ] **Editor de Alertas in-app** (Editor-gated): CRUD reglas + tabla `by_role` +
      panel de **backtest** (últimos N días) + versionado.

## Fase 2 — Constructor de paneles (P3) + CK (§4)

> ACWR / P5 se movió a **Fase 1** (decisión "todo junto" de §1).
- [ ] CK (§4) — extender `TEAM_LEADERBOARD`: **altura = desviación (Z/CV con signo)
      por defecto** (toggle `height: deviation|value`), color = semáforo por desviación
      (`stats.py`), valor crudo en etiqueta/tooltip, ordenable por desviación; `status`
      por-barra en el resolver + color por-barra en `TeamLeaderboard.tsx`;
      estadístico/ventana/umbrales en `display_config` (panel builder); líneas 200/500 off.
- [ ] CK por jugador: overlay de media móvil ± SD (banda) en la línea del perfil,
      reusa `stats.py`. (4)
- [ ] CK alerta opcional: regla `zscore` sobre `ck.valor` (reusa el motor de Fase 1). (4)
- [ ] **Constructor de paneles in-app — modo edición WYSIWYG** (extiende "Promover
      al panel"): toggle **"Editar panel"** en la **propia superficie** (no una
      sección de config aparte), rol **Editor**. En modo edición: **agregar** widget
      (tipo de gráfico → data source → líneas/zonas/coloreo → **preview**), **mover**
      (drag), **redimensionar** (`column_span`), **editar/eliminar** inline; guardar
      persiste en el layout. (4, 2, reduce dependencia de 6)
- [ ] Disponible en **ambas** superficies: reporte de equipo (`/reportes/[dept]`) y
      **tab de departamento del jugador**.
- [ ] **Banner de alcance** en el editor del tab de jugador: el layout es por
      `(departamento, categoría)`, así que editar aquí **aplica a toda la categoría**
      (principio IA #5, evita el footgun del promote actual §3.53). Los dashboards
      **por jugador individual quedan fuera de alcance** (serían overrides
      por-jugador — feature mayor aparte).
- [ ] Endpoints de edición de layout (CRUD secciones/widgets/data-sources) +
      guardrails (preview, versionado/auditoría, "restaurar default"); gate Editor.

## Fase 3 — Modelo clínico (P4 + esquema)

- [ ] `Episode.available_at` (migración) + ruta de escritura (extender
      `PATCH /episodes/{id}` / `EpisodePatchIn`) + serializer + UI. (3.1)
- [ ] Expandir `stage` a las 6 fases + `option_labels` en la plantilla `lesiones`
      (config). (3.1)
- [ ] Mapa `stage → Player.status` **config-driven** en `episode_config` (reemplaza
      el `_map_stage_to_player_status` hardcodeado; editable en Django Admin);
      default por la tabla acordada; **sin migración del enum** (4 buckets). (3.1)
- [ ] Etiqueta secundaria de fase fina (del `stage` del episodio abierto) en roster
      + Daily, sin tocar `Player.status`. (3.1)
- [ ] Re-anclar el conteo de baja a `available_at` (fallback `ended_at`) en
      `daily_report._lesionado` + PDFs de lesiones. (3.1)
- [ ] §3.2 — `help_text`: `expected_return_date` = pronóstico de disponibilidad al
      diagnóstico; real = `available_at`. (config)
- [ ] Lectura "historial de pronóstico" (serie de `expected_return_date` por
      resultado del episodio) + fix del prefill en `InjuryPanel` (previo read-only +
      acción explícita "actualizar pronóstico"). (3.2)
- [ ] Agregación de desviación: por episodio `error_dias = available_at − primer
      expected_return_date`; por depto/período **sesgo** (media con signo) + **MAE**;
      endpoint + widget de reporte Médico (panel builder). Sin migración. (3.2)
- [ ] Objetivos de dos tipos (7.3): `Goal.template/field_key/operator/target_value`
      → nullable + campo `title`; migración. Evaluador saltea goals sin métrica en
      `sync_evaluate_for_result`.
- [ ] `AlertSource.GOAL_OVERDUE` (nuevo): en el tick diario, objetivo libre vencido
      y sin cerrar → alerta **persistente** en la campana del navbar; **no**
      auto-`missed`; auto-descarte al cerrar el objetivo; exenta del barrido de 30 d.
- [ ] `POST /goals` valida por tipo; `PATCH /goals/{id}` permite cierre manual de
      objetivos libres a `met` **o** `missed` (+ `cancelled`) y descarta la alerta.
- [ ] Front: toggle "Con métrica / Libre" en `GoalForm`; tarjetas libres con
      "Marcar cumplido" / "Marcar no cumplido" / "Cancelar".

## Fase 4 — Pulido

- [ ] Bump de modelo IA (`config/settings.py` + ~8 fallbacks) + vocabulario de
      gráficos más amplio + path de ratio/calculado. (6)
- [ ] Lanzador **"Subir datos"** en el sidebar, **bajo el grupo "Datos"** (junto a
      "Exportar datos" / "Uso"): menú anidado Subir datos → Departamento → Exam
      Template (reusa el patrón de grupo expandible de `Sidebar.tsx`; escopeado a la
      categoría; solo rol Editor). (7.1)
- [ ] `GET /api/templates?category_id=&department=` — plantillas por departamento,
      escopeadas por membresía (hoy solo existe el listado por jugador). (7.1)
- [ ] Modal de captura que despacha por `input_mode` (`TeamTableForm` /
      `DynamicUploader`+selector de jugador / `BulkIngestForm`); reusa componentes
      existentes. (7.1)
- [ ] Simetría con "Exportar datos" (§5): árbol Departamento → Template
      compartido; considerar construir el par junto. (7.1)

## Decisiones — estado

### ✅ Resueltas

- [x] **Export (#5)** — XLSX ancho, fila = jugador-fecha, **una hoja por examen**
      (calculados incluidos); menú = grupo **"Datos"** = "Subir datos" +
      "Exportar datos" (rol Editor) + "Uso" (solo superuser).
- [x] **Adherencia de wellness (#2)** — vista **solo informativa** (sin alerta);
      lista de hoy sin denominador; período con denominador **auto-calibrado**
      (días con actividad de check-in). No depende del calendario de entrenamientos.
- [x] **Objetivos (#7.3)** — dos tipos: **con métrica** (auto-evaluados) o **libres**
      (texto + fecha, cierre manual); se extiende `Goal`. La lista deja de estar
      limitada a campos numéricos.
- [x] **Deep-link / CTA (#7.2)** — la disyuntiva tab-vs-formulario queda
      **superada** por el rediseño de tarjeta (botones "Ver info" / "Agregar a
      plan").
- [x] **Objetivo libre vencido (#7.3)** — **cierre manual** (nunca auto-`missed`);
      al vencer sin cerrar dispara una **alerta persistente en la campana**
      (`AlertSource.GOAL_OVERDUE`) que se mantiene hasta que el usuario lo marca
      cumplido / no cumplido / cancela.
- [x] **Estados de lesión (#3.1)** — **Opción A + mapa configurable:** 6 fases en
      `stage` (config) → colapsan a los 4 buckets de `Player.status` vía un mapa
      **editable en Django Admin** (`episode_config`), **sin migración del enum**;
      fase fina como etiqueta secundaria. Default: aguda→injured, intermedia→recovery,
      reintegro/reintegro+parcial/RTT→reintegration, RTP→available.
- [x] **Tarjeta de sugerencia — gráfico y números (#7.2)** — gráfico **derivado del
      tipo de alerta** (línea temporal + overlay; tabla para cualitativo); números
      **backend-enriquecidos**; el LLM conserva solo la recomendación / CTA. Arregla
      de paso §6.

### ⏳ Abiertas

- **Ninguna.** Todas las decisiones de diseño están cerradas — el documento queda
  **decision-complete** para empezar a construir. (Las plantillas/umbrales que el
  club editará por su cuenta se resuelven en runtime vía config, no acá.)

> **Arranque de Fase 0:** los quick-wins (bug de anclaje de carga semanal, fix del
> slug del KPI, endpoint/vista de export, `player_ids` en briefing) **no dependen**
> de ninguna decisión abierta y pueden empezar ya.

## Seguridad (fuera de fase, hacer ya)

- [ ] 🔴 Rotar el `ANTHROPIC_API_KEY` commiteado en `backend/.env` y sacarlo del repo.

---

*Última actualización: 2026-07-13. Referencias de código a verificar contra el
árbol actual al implementar cada ítem.*
