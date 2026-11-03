# Plan — Control de carga (vistas que responden preguntas)

> Etapa: **investigación** (2026-11-03). Nada implementado todavía.
> Fuentes: `Qué queremos del dashboard.pdf` (Área Física · Fútbol Formativo,
> 18 láminas) + el artifact del club "Control de Cargas-U20" (v115),
> analizado por código completo y renderizado con datos sintéticos
> (capturas en el scratchpad de la sesión, 34 vistas × móvil/escritorio).

---

## 1. Qué piden, en una línea

**"Menos datos, más respuestas."** Cada pantalla contesta una pregunta del
cuerpo técnico, en el celular, en la cancha, en menos de 10 segundos:
*¿cumplió la semana?, ¿a quién compensar?, ¿quién llega fatigado?*

| # | Pestaña (PDF) | Pregunta | Cómo la quieren ver |
|---|---|---|---|
| 1 | Resumen | ¿Cómo está el plantel hoy / esta semana? | Tarjetas semáforo + número, una frase de conclusión arriba, detalle plegado |
| 2 | Carga GPS | ¿Cuánto hicimos en cada sesión? ¿Cortos, pasados, bien? | Filtros arriba → resumen plantel vs óptimo → fila por jugador (óptimo/real + %) → cortos y pasados → Top 3 → tabla de óptimos al final |
| 3 | Control de carga | ¿Llega fatigado al partido? | Δ% RSI primer día vs último día del microciclo, barras de peor a mejor, rojo ≤ −5% |
| 4 | Check-in / out | ¿Cómo llega, cómo se siente, qué le molesta, cómo se va? | Primero alertas (con puntaje), después evolución: barras por ítem 1–5 + línea total bienestar (/25) + línea muscular (/10); check-out: barras minutos + línea RPE |
| 5 | Kinesia y lesiones | ¿Quién está en readaptación o clínica? | Lista corta, color por estado, fecha estimada de retorno |
| 6 | Minutos y asistencia | ¿Cuánto jugó y a cuántas sesiones fue? | Tabla por jugador, barras simples, semáforo sólo donde hay problema |
| 7 | Jugador | ¿Cómo viene esta persona en todo? | Foto/posición/categoría, selector 1 o varios microciclos, tabla por día MD óptimo/real, secciones plegadas (bienestar, saltos, evaluaciones, composición) |
| 8 | Evaluaciones | ¿Qué tan fuerte/rápido/resistente vs grupo y vs su anterior? | Tabla por test: valor, Δ vs anterior, flecha; 7 niveles por edad (cortes del club) |
| 9 | Composición corporal | ¿Cómo evoluciona músculo, grasa, Σ pliegues? | Línea por jugador + tabla ordenable del grupo |

**Reglas de presentación** (lámina "Cómo lo queremos ver" + "Qué no queremos"):
óptimo / real en una línea y % debajo · color **+ número + texto**, nunca sólo
color · ordenar por lo que hizo, no por % · *sin dato ≠ cero* · al pie de cada
cuadro, qué datos usó · lo secundario plegado · glosario a un toque · comparar
por posición, nunca contra todos · filtros que no se reinician solos.

## 2. Lo que aprendimos del artifact del club

Es la referencia real de cómo trabajan; el PDF es la versión "pedida a
ingeniería". El artifact es más rico que el PDF.

**Estructura (layout C, único alcanzable):** selector de categoría (S20 / S18 /
S16 / S15) → 8 pestañas: Resumen, Plantel, Check-in/out, Partidos, Tendencias,
Jugador, Evaluaciones, Antropometría. Mobile-first (`max-width: 760px`).

**El concepto central es el óptimo por (posición × día MD × métrica):**
`targets/profiles = {t: {DFC: {"MD-4": [DT, HSR, SPR, ACC, DEC]}, …}}`, con un
juego distinto para S18. Las métricas son 5 con objetivo — DT, HSR >20, SPR >25,
ACC >3, DEC <−3 — más Vmáx y duración informativas.

**Fórmulas y umbrales que usa (verificados en el código):**

| Concepto | Regla |
|---|---|
| Δ% | (real − óptimo) / óptimo × 100 |
| Semáforo de celda | verde \|Δ\| ≤ 8% · ámbar < −8% · rojo > +8% |
| Cortos | ≥ 3 métricas < −8% |
| Pasados | alguna métrica > +20% |
| Top 3 / más alejados | media de \|Δ\| sobre las 5 métricas; sólo jugadores con ≥ 60% de los minutos del que más jugó |
| Falta para completar la semana | Σ óptimo de los días planificados (`plans/{semana}.days`) − Σ real |
| Fatiga neuromuscular | RSI R-CMJ (rebote/contacto, mejor de 2 intentos) PRE vs POST; rojo ≤ −5%, ámbar < 0 |
| "Para revisar" | fatiga RSI ≤ −5% · sobrecarga (≥2 core > +20% mismo día) · bajo 2 días seguidos · salto brusco de DT · desentrenado / sobreentrenado semanal · dolor · bienestar ≤ 2 |
| U invertida | pico en MD-4 o MD-3, MD-1 < 85% del pico, MD+2 < pico |
| Carga dinámica (ficha) | (promedio últimos 4 MD oficiales + máximo histórico) / 2 |
| UA | minutos × RPE |
| Evaluaciones | 7 niveles, 6 cortes por test y por edad (18-20, 15-16); en tiempos menos es mejor |

✅ **Bandas — decidido (2026-11-03), reemplaza tanto al PDF como al artifact:**

| \|Δ%\| vs óptimo | Estado | Color |
|---|---|---|
| ≤ 8% | En objetivo | verde |
| > 8% y ≤ 12% | Alerta leve | amarillo |
| > 12% | Alerta grave | rojo |

- **Simétrica**: pasarse y quedarse pesan igual; la dirección va en texto
  ("bajo" / "sobre") y en el signo, no en el color.
- **Alertas por día**: se muestran todas las del día (todos los que salen de la
  banda, ordenados por cuánto). No se replican las listas del artifact
  ("pasados" > +20%, "cortos" ≥ 3 métricas).
- **Objetivos chicos** (p. ej. sprint en MD-1): el efecto de % inflado se
  considera despreciable; sin margen mínimo en unidades.
- **Principio rector del club: que la mayoría de los elementos sean
  configurables.** Umbrales (8 / 12), simetría, métricas evaluadas, ventana
  (28 d), corte de minutos (75'), posiciones → todo en `LoadControlConfig`
  por club/categoría (y por métrica donde aplique), con estos valores como
  default.

**Patrones de UX que vale la pena copiar tal cual:** "Datos usados:" al pie de
cada tarjeta (microciclo, días, con/sin partido, N jugadores, exclusiones);
avisos de dato parcial ("Sólo 3 de 5 días con GPS") en vez de ceros; conteo
●verde/●ámbar/●rojo de jugadores bajo cada KPI; incluir/excluir jugadores del
promedio; con / sin partido en el acumulado; toggle Total / Por minuto; tocar
un nombre en cualquier parte abre la ficha; glosario de ~50 términos.

**Cómo se alimenta hoy:** a mano. El club empuja sesiones, óptimos, tests y
wellness a la base del artifact (el `liveLoad` desde su Google Sheet está
desactivado). **Las fuentes son las mismas que SLAB ya ingiere:** los headers
de GPS que mapea `formativo_gps_ingest.py` son exactamente `HSR (m) >20km/h`,
`AC (#) >3ms2`, `SPRINT (m) >25km/h`, y el check-in/out sale del mismo
formulario. SLAB puede reemplazar su pipeline manual — esa es la propuesta de
valor, no sólo "gráficos más lindos".

## 3. Por qué SLAB no les sirve hoy

1. **Los layouts son centrados en el campo, no en la pregunta.**
   `generate_formativo_layouts` crea un gráfico de línea por cada campo con
   datos (20 layouts de jugador / 245 widgets, 20 de equipo / 171 widgets). Es
   literalmente "el dashboard que muestra todo" de la lámina 2.
2. **No existe el óptimo.** No hay modelo de carga planificada ni de objetivo
   por (posición × MD × métrica). Sin eso no hay %, ni cortos/pasados, ni
   "falta para completar". Es el hueco #1.
3. **Un widget = una plantilla.** `WidgetDataSource` lee un template; las
   preguntas del club cruzan GPS + óptimo + plan + wellness + RSI + minutos.
4. **El microciclo no es navegación.** Tenemos `md_label` (≈99% de las filas
   SUB-20) y `microciclo` (≈90%) como campos, pero la UI navega por rango de
   fechas + chips MD. Ellos piensan en "M42, acumulado, con partido".
5. **No hay lógica de excepción.** Nuestros widgets muestran series; ellos
   quieren "quién se salió, ordenado por cuánto".
6. **Escritorio primero, sin "datos usados", sin glosario.**
7. **Equipo vs cohorte.** Ellos piensan en S20/S18/S16/S15 (el equipo que
   compite); SLAB modela cohortes (Serie 2008…) y el equipo sólo aparece vía
   `display_config.team`.

Lo que **sí** tenemos y se reutiliza: ingest de GPS y wellness desde las
planillas, `md_label` / `microciclo` / `exams/microcycle.py`, Centro de mando
(KPIs, plantel), Daily (lesionados, retorno estimado, GPS vs semana habitual),
MD+2 (semáforo CMJ vs basal), `EvaluationGrid` + `seed_formativo_bands` (los 7
niveles por edad **ya existen**), `ficha_partido` (minutos COMET), lesiones +
`Episode`, pentacompartimental, `lib/deltaTone.ts`.

## 4. Recomendación

**No estirar los Department Layouts.** Construir un módulo propósito-específico
**"Control de carga"**, igual que hicimos con Centro de mando, Daily y MD+2 (las
pantallas que sí se usan), sobre dos piezas nuevas de dominio y un set chico de
primitivas compartidas.

- Los layouts genéricos se quedan para exploración, pero en el formativo se
  **degradan** (sacarlos del menú principal de Físico una vez que exista el
  módulo) y se deja de autogenerar "una línea por campo".
- Las primitivas, una vez probadas, se pueden exponer como `chart_type`
  nuevos (`target_matrix`, `exception_list`) para que otros clubes compongan.
  **Primero probar, después generalizar.**
- El módulo es agnóstico de categoría: Primer Equipo ya tiene GPS Catapult con
  `md_label`; si entregan sus óptimos, las mismas pantallas les sirven.

### 4.0 Módulo de planificación — decidido (2026-11-03)

El óptimo **no es una tabla fija**: es el objetivo de cada microciclo, y se
arma así (modelo de trabajo actual del PF):

```
Referencia de partido  = promedio, por POSICIÓN y por métrica, de los jugadores
                         con > 75 min de GPS en los partidos de los últimos 28 días
Plan del microciclo    = % por DÍA MD y por MÉTRICA (lo ingresa el profesor)
Óptimo del día         = referencia × %
```

| Decisión | Valor |
|---|---|
| Nivel de la referencia | **Por posición** (DFC, LAT, MC, EXT, DC). Si una posición no tiene ningún jugador > 75' en la ventana → cae a la referencia del equipo, y se dice en "datos usados". |
| Ventana | **28 días, sólo partidos** (`gps_partido`; las sesiones `tipo_sesion=amistoso` de `gps_sesion` no entran). |
| % | **Por día MD y por métrica** (5 métricas × ~7 días). Cada microciclo parte copiado del anterior. |
| Corte de 75' | **Duración del GPS** (`tot_dur`), no los minutos de COMET. |
| Congelamiento | **Sí**: la referencia se fotografía al abrir el microciclo; un partido nuevo no reescribe semanas cerradas. |

**El microciclo va de partido a partido, no es una semana calendario**
(decidido 2026-11-03). `MD AMISTOSO` es día de partido y **corta el
microciclo**: la planificación debe admitir **partidos intermedios** (oficiales o
amistosos) dentro de la semana — p. ej. `M40 CLOA` + `M40 UE`. Cada día se
etiqueta MD±n respecto del partido más cercano y el % del PF se aplica a esa
etiqueta. El día de amistoso vale 100% en la evaluación, pero su GPS **no** entra
en la referencia (sólo oficiales). El nº de microciclo (`MICRO`) y su tipo
(`TIPO`: MIXTA / PROFUNDIDAD / AMPLITUD) ya vienen en las pestañas de categoría
de "GPS CATEGORÍAS".

**Sparring y compensación (revisado en "GPS CATEGORÍAS", 2026-11-03):**
- *Sparring* sí se registra: pestaña `SPARRING` (**651 filas reales**; las
  ~1.980 de la grilla eran filas vacías con la categoría prellenada) + filas de
  categoría con OBSERVACIÓN "SPARRING". SLAB ya las tenía todas (650 + 1
  duplicado). ✅ Desde la rebanada 1 se marcan con `es_sparring`.
- *Compensación* **no se registra**. Sólo 36 filas "POST PARTIDO" (`NO MD`,
  2–8 min). El módulo calcula la **necesidad** de compensar (brecha del día MD);
  si el club quiere cerrar el ciclo, que marque `COMPENSACIÓN` en OBSERVACIÓN.

No reutiliza `match_load_refs` (`dashboards/player_state.py:243`): ese es
individual y toma el **máximo**; éste es de grupo y toma el **promedio**. Mismo
corte de 75', cálculo nuevo. El radar y la alerta `pct_match` no cambian.

### 4.1 Dominio nuevo (backend)

| Pieza | Forma propuesta | Notas |
|---|---|---|
| `MicrocyclePlan` | (equipo, lunes de la semana) → días planificados + partido + `ref_snapshot` `{POS:{métrica: valor, n_jugadores, n_partidos}}` congelado al abrir | Días por defecto inferidos del fixture (`exams/microcycle.py`); el PF marca descanso / doble sesión. Habilita "falta para completar". |
| `MicrocyclePlanDay` | (plan, `md_label`) → `{métrica: %}` | Óptimo = `ref_snapshot[pos][métrica] × %`. "Copiar microciclo anterior" como acción por defecto. Editable por el PF (guardrail de Editor). |
| `LoadControlConfig` | por club/categoría (override por métrica): tolerancia verde (8), límite leve/grave (12), simetría, métricas evaluadas, ventana de referencia (28 d), corte de minutos (75'), grupos de posición, RSI rojo (−5), mínimo de minutos para rankings (60%) | El club pidió que casi todo sea configurable; los valores decididos son el default. |
| Grupo de posición | DFC, LAT, MC, EXT, DC | Mapear sobre `Position.role`/abreviatura; el óptimo es por grupo. |
| Fatiga post-partido (salto) | **Decidido 2026-11-03:** PRE = MD-1 · POST = MD+1 (sin POST2, ver «Fuente de saltos»); muestra = jugadores con > 75'; métrica principal recomendada **CMJ RSI-modified** (+ altura, FT:CT), CMRJ `Rebound RSI (JH/Contact Time)` opcional; métrica y umbrales (≥0 / −5) configurables | **VALD (revisado 2026-11-03):** trae ambos (CMJ y CMRJ con RSI), pero el formativo **casi no mide ahí desde ago-2026** (SUB-20: 2 CMJ + 1 CMRJ; Series 2008-10: 0; último bloque CMRJ mar-2026). Primer Equipo sí mide CMJ en MD+1/MD+2. Falta saber con qué miden hoy el formativo (el artifact usa caída/contacto/rebote). Reutilizar la pantalla MD+2 (CMJ vs basal). Pestaña renombrada **"Fatiga post-partido"**. **Decisión: seguir con el instrumento actual** (no VALD). Ver «Fuente de saltos» más abajo. |

#### Fuente de saltos — planillas del club (revisadas hoja por hoja, 2026-11-03)

8 Google Sheets `U{11,12,13,14,15,16,18,20}_Plantilla_control_carga_CMJ`, legibles
por nuestra cuenta de servicio `slab-uchile-gdrive@…` (la misma de GPS/wellness).
**Una hoja por microciclo** (`M1`…`M46`; variantes `SEMANA SANTA M13`, `LLUVIA`,
`Viaje a mendoza`, `CONTROL DE PESO`) y **una hoja por partido** cuando hay dos en la
semana (`M40 CLOA` / `M40 UE` en U20 = `M39 CLOA` / `M39 UE` en U18 → **la
numeración de microciclos difiere por categoría**). La hoja `Totales` es un
consolidado con fórmulas rotas (`#REF!`): no se usa.

| | |
|---|---|
| Cobertura real | U20, U18, U16, U15: semanal M2/M3 → M40–M42 (ene–oct 2026), ~12–30 jugadores por hoja. U13/U14: sólo M6–M22. U11/U12: vacías. |
| Instrumento | ene–mar: **alterna VALD CMJ y OptoJump CMJ**; desde ~M9–M12: **OptoJump R-CMJ** sin excepción (por eso VALD se vació). |
| Columnas CMJ | Altura de salto · RSI Mod · Ecc velocity, cada una `PRE 1 · PRE 2 · BEST PRE · POST 1 · POST 2 · BEST POST · Δ%` (1 y 2 = **intentos**, no momentos). BEST = **máximo**. |
| Columnas R-CMJ | Altura de caída (1er salto, m) · Tiempo de contacto (s) · Altura del rebote (m) (en semanas tempranas: Tiempo de vuelo) + `RSI PRE · RSI POST · Δ%`. RSI = altura rebote ÷ contacto. ⚠️ Aquí BEST = **promedio** de los 2 intentos, no máximo. |
| Celda A1 | desde ~M35: tipo de microciclo **PROFUNDIDAD / MIXTA / AMPLITUD** (→ guardarlo en `MicrocyclePlan`). |
| Sin fecha ni MD | La fecha sale del nº de microciclo + categoría (cruzable con `microciclo` de `gps_partido`). |
| Sin POST2 | Sólo PRE y POST por hoja. |
| Bandas RSI (R-CMJ) del club | Deficiente 0,8–1,2 · < Media 1,2–1,4 · Media 1,4–1,8 · > Media 1,8–2,1 · Bueno 2,1–2,5 (rojo → verde; = las del artifact). Se cargan como regla BAND (mismo mecanismo que `seed_formativo_bands`, editable en la app), extremos abiertos, borde al tramo superior. La banda colorea el **nivel**; la alerta de fatiga sale del **Δ% PRE→POST**. ✅ Confirmado: extremos abiertos (< 0,8 = Deficiente, > 2,5 = Bueno) y **mismos cortes en U15, U16, U18 y U20** (capturas del club); se instancian por categoría para poder ajustarlas por separado. |
| Extras | Filas bajo la nómina (citados/refuerzos), fila `PROMEDIO` (= `MEDIAN(D3:D34)`, excluye a los extras), columnas de peso en algunas semanas. `Q1PQ` = texto suelto en U20 `M38 `!T48 y `M39`/`M40 CLOA`/`M40 UE`!T49 → ignorar. |
| **Decidido** | **Sólo PRE y POST** (no hay POST2). La celda A1 **es el tipo de microciclo** (PROFUNDIDAD / MIXTA / AMPLITUD) → campo de `MicrocyclePlan`. Valor por intento por defecto = **mejor intento** (como su dashboard), configurable; difiere del "BEST" = promedio de la planilla R-CMJ → explicarlo en "datos usados". |
| Errores visibles | `#DIV/0!` cuando falta dato; el consolidado muestra −100% si falta el POST (sin dato ≠ cero). |
| Sparring / compensación | flags en `gps_sesion` (`tipo_sesion` ya existe) | Confirmar con el club cómo lo marcan en la planilla. |

Servicio central: **`load_vs_target`** — dado (equipo, microciclo, día |
acumulado, con/sin partido, jugadores incluidos) devuelve por jugador × métrica
`{óptimo, real, Δ%, banda, días_con_dato, días_esperados}` + agregados del
plantel + conteos por banda + la lista "datos usados". Todo lo demás (Resumen,
Plantel, Partidos, Tendencias, ficha) consume esto. Se valida con **paridad
contra el artifact**: mismo microciclo, mismos números (como hicimos con
pentacompartimental).

Motor de excepciones: **`load_flags`** — las reglas de "Para revisar" como
funciones puras con umbrales de `LoadControlConfig`, que devuelven
`{tipo, jugador, severidad, texto}`. Más adelante pueden alimentar `Alert`.

### 4.2 Primitivas de UI (frontend)

`<QuestionHeader>` (la pregunta como título) · `<LoadFilters>` (equipo,
microciclo, día MD / acumulado, con/sin partido — **todo en la URL**, principio
IA #2) · `<TargetCell>` (óptimo / real + % + texto de banda; nunca sólo color) ·
`<BandCounts>` (●●●) · `<ExceptionList>` (sólo los que se salen, ordenados por
cuánto) · `<DataProvenance>` ("Datos usados: …") · `<Glossary>` (modal único,
términos por clave) · `<Collapsible>` · `<PartialDataNote>`.

### 4.3 Pantallas

Ruta `/control-carga?tab=…` (pestañas sincronizadas a la URL), mobile-first.

| Tab | Responde | Construye sobre |
|---|---|---|
| `resumen` | ¿Cómo está el plantel? | `load_vs_target` semana + `load_flags` + check-in de hoy + disponibles (Centro de mando) |
| `carga` | ¿Cumplió? ¿Cortos/pasados? Top 3 | `load_vs_target` día/acumulado; tabla óptimos al pie |
| `fatiga` | ¿Llega fatigado? | `rcmj_microciclo` (nuevo) — barras Δ% RSI peor→mejor |
| `bienestar` | ¿Cómo llega / cómo se va? | `checkin_formativo` / `checkout_formativo` (scoring ya en `api/wellness.py`) |
| `disponibilidad` | ¿Quién está en readaptación? | Daily §Lesionados (`Episode`, `expected_return_date`) |
| `minutos` | ¿Cuánto jugó / asistió? | `ficha_partido` + presencia GPS/check-in como proxy de asistencia |
| `partidos` | ¿Cómo cargamos en partido? | `gps_partido` + óptimo MD + minutos |
| `tendencias` | ¿Forma del microciclo? ¿U invertida? | `load_vs_target` por día × microciclo (hasta 3) |
| Ficha | ¿Cómo viene este jugador? | Nueva pestaña "Carga" en `/perfil/[id]` + secciones plegadas que reutilizan lo existente |
| Evaluaciones | ¿Mejoró o empeoró? | `EvaluationGrid` + Δ vs anterior y flecha |
| Composición | ¿Músculo y grasa? | pentacompartimental — ⚠️ hoy no aplica a categorías formativas (1.165 resultados fuera de todo dashboard, `ESTADO_FORMATIVO.md` §5) |

## 5. Etapas (alineadas a la lámina 18 del club)

**Etapa 0 — Cerrar decisiones con el club (antes de escribir código).**
Ver §6. Entregable: óptimos reales S20 y S18 en su formato, umbrales
confirmados, un microciclo de referencia con sus números del artifact.

**Etapa 1 — Base.** `LoadTarget` + `MicrocyclePlan` + `LoadControlConfig` +
import de óptimos; servicio `load_vs_target` con test de paridad; selector de
equipo S20/S18 de primera clase; pestaña **Carga GPS** completa (filtros,
resumen, fila por jugador, cortos/pasados, Top 3, referencia).
*Listo cuando:* el PF responde "¿cumplió la semana?" en < 10 s en el celular y
los números calzan con el artifact.

**Etapa 2 — Decisión.** `load_flags`; pestaña **Resumen** (frase de
conclusión determinística, sin LLM — el resumen IA se sacó del Centro de mando
por costo sin lectores, 4492ab3); **Tendencias** (perfil del microciclo + U
invertida); pestaña **Carga** en la ficha del jugador (tabla por día MD,
varios microciclos, carga dinámica).

**Etapa 3 — Salud.** Plantilla + import `rcmj_microciclo` y pestaña
**Fatiga**; **Bienestar** (alertas primero, después los dos gráficos);
**Disponibilidad**; **Minutos y asistencia**; **Partidos**.

**Etapa 4 — Perfil.** Evaluaciones con Δ vs anterior; Composición corporal
(ampliar aplicabilidad de pentacompartimental); export PDF de la ficha
(el artifact ya tiene "Informe interno" e "Informe para selección").

Cada etapa se prueba con datos reales en una demo con el PF antes de la
siguiente (lo pide el propio PDF).

## 6. Preguntas — estado (2026-11-03)

| # | Tema | Estado |
|---|---|---|
| 1 | Óptimos | ✅ No es tabla fija: **módulo de planificación** (referencia de partido por posición × % por día y métrica del PF) — §4.0 |
| 2 | Banda verde | ✅ ≤ 8% en objetivo · 8–12% leve · > 12% grave, simétrica, configurable — §2 |
| 3 | Plan de la semana | ✅ Lo arma el PF en la planificación; microciclo de partido a partido, admite partidos intermedios (amistoso corta) — §4.0 |
| 4 | RSI | ✅ Planillas `U*_Plantilla_control_carga_CMJ` (OptoJump R-CMJ), PRE = MD-1 / POST = MD+1, bandas del club — «Fuente de saltos» |
| 5a | Sparring | ✅ Pestaña `SPARRING` de "GPS CATEGORÍAS"; **suma a la carga del jugador**, interruptor para el promedio del equipo |
| 5b | Compensación | ⏳ No se registra. **El club va a marcar `COMPENSACIÓN` en OBSERVACIÓN** (lo pide Jorge). Mientras, SLAB muestra la necesidad |
| 6 | Asistencia | ✅ **Presencia en GPS** (el check-in no lo contestan todos) |
| 7 | Grupos de posición | ✅ DEFENSA CENTRAL→DFC · DEFENSA LATERAL→LAT · MEDIOCAMPISTA→MC · EXTREMO→EXT · CENTRO DELANTERO→DC · GUARDAMETA→POR (fuera por defecto); configurable |
| 8 | "JARVIS" | ✅ Sólo un nombre provisorio del artifact. La frase de conclusión del Resumen será determinística (sin LLM) |

## 7. Riesgos

- **El óptimo es del club.** Si la tabla no se mantiene, todo el módulo
  miente con apariencia de verdad — por eso `valid_from` y "datos usados"
  muestran qué óptimo se usó.
- **Latencia de datos**: el valor está en el día. Revisar la cadencia del sync
  de planillas (GPS y wellness) contra su horario de uso (07:00–14:00).
- **Homónimos / nombres** entre la planilla y el plantel (ya visto en
  `PENDIENTES_CLUB.md`).
- **Alcance**: el artifact tiene ~8 pestañas con muchos toggles. Copiar todo
  reproduce el problema que el PDF denuncia. Empezar por las tres preguntas del
  criterio de éxito y sumar sólo lo que se use.

## 8. Diseño técnico — Etapa 1 (Planificación + Carga GPS)

> Propuesta, sin implementar. Maqueta para validar con el PF:
> https://claude.ai/artifact/QBaQ1xdxdK8FkTZhai3e7G (privada hasta compartirla).

### 8.1 Hechos del código que condicionan el diseño

- **No existe un modelo "equipo U18".** Un equipo es `(club, temporada, Bracket)`:
  todas las `Category` con `TeamSeason(season, bracket)` iguales
  (`core/models.py:361`). `dashboards/team_scope.py:42` ya resuelve filas y
  plantel de un equipo (`origen_hoja = "U18"` o `event__bracket`). → El
  microciclo se ancla a **(club, season, bracket)**, no a `Category`.
- **Los amistosos no tienen `Event`**: son `gps_sesion` con
  `tipo_sesion = "amistoso"` (`exams/formativo_gps_ingest.py:650`). `Event`
  no distingue oficial/amistoso. → El **plan es la fuente de verdad** de qué
  día es partido; se pre-llena con los `Event` oficiales del bracket + los
  códigos `MD AMISTOSO` del GPS.
- `exams/microcycle.py` etiqueta MD con los partidos de la **categoría del
  jugador** y respeta `md_label_source = "club"`. La evaluación cruza **por
  fecha**, no por etiqueta, así que no depende de eso.
- El ingest GPS **descarta** hoy `POSICIÓN` (`NO_METRICAS`, :115) y `TIPO`
  (no hay clave), y no marca sparring ni compensación.
- `Position.role` es el único agrupador existente (texto libre).
- Patrones a copiar: endpoints django-ninja en `api/routers.py` con lógica en
  `api/<modulo>.py` (como `api/md2.py`); permisos de pantalla en
  `Category.Meta.permissions` + migración tipo `core/0028` + `seed_role_groups`;
  `@require_perm`; front `md2/page.tsx` (estado en URL, `useToast`,
  `useConfirm`, `api<T>()`), `RequirePermission`, `STATIC_NAV` en el sidebar,
  `SEGMENT_LABELS` en Breadcrumbs.

### 8.2 Modelos (app nueva `load_control`)

| Modelo | Campos clave |
|---|---|
| `LoadControlConfig` | `club` (1:1), `overrides` por bracket (JSON). Defaults: `band_ok=8`, `band_mild=12`, `symmetric=True`, `metrics=[tot_dist,hsr,sprint_dist,acc,dec]`, `ref_window_days=28`, `ref_min_minutes=75`, `ref_official_only=True`, `include_sparring=True`, `attempt_value="best"`, `rsi_alert={ok:0, grave:-5}`, `position_groups={DFC:{label, sheet_labels:["DEFENSA CENTRAL"], position_ids:[…]}, …}`, `excluded_groups=["POR"]`. |
| `Microcycle` | `club`, `season`, `bracket` (= el equipo), `number` (MICRO del club), `kind` (mixta / profundidad / amplitud / adaptación / competencia — lista configurable), `start_date`, `end_date`, `status` (borrador / abierto / cerrado), `copied_from` (FK self), `ref_snapshot` JSON `{grupo:{métrica:{value, n_players, n_matches, fallback}}}`, `ref_window` (desde/hasta), `frozen_at`, `created_by`. Único por (club, season, bracket, number). |
| `MicrocycleDay` | `microcycle`, `date`, `kind` (entrenamiento / descanso / oficial / amistoso), `md_label` (calculado al guardar: partido más cercano dentro del microciclo y sus vecinos), `event` (FK nullable), `targets_pct` JSON `{métrica: %}` (vacío en partido = 100). Varias filas de partido por microciclo = **partido intermedio**. |

`ExamResult.result_data` del GPS gana: `posicion_hoja`, `tipo_microciclo`,
`es_sparring` (hoja `SPARRING` u OBSERVACIÓN "SPARRING"), `es_compensacion`
(OBSERVACIÓN contiene "COMPENSACI"). Backfill re-corriendo el ingest
(idempotente por `origen_id`). ✅ Hecho en local (rebanada 1, 2026-11-03):
18.227 filas con posición, 659 sparring, 1.981 con tipo. `TIPO` trae **5
valores**: mixta, amplitud, profundidad, **adaptación** y **competencia**.

### 8.3 Servicios

- `load_control/reference.py` · `compute_reference(club, season, bracket, anchor, cfg)`
  → por grupo y métrica: promedio de `gps_partido` del equipo (vía
  `team_scope`) en `[anchor − 28 d, anchor)`, `tot_dur ≥ 75`, sin
  `match_type = friendly`; grupo sin muestra → promedio del equipo,
  `fallback=True`. Se congela en `ref_snapshot` al pasar a "abierto".
- `load_control/evaluation.py` · `load_vs_target(microcycle, date | "acumulado", include_sparring)`
  → por jugador × métrica `{target, real, pct, band, has_data}`. Real = suma de
  las filas GPS del jugador ese día (sesión + partido + sparring +
  compensación). Target = `ref_snapshot[grupo][m] × pct`. Sin GPS = "sin
  datos", nunca cero. Además: promedio del plantel, conteo por banda, alertas
  del día (todos fuera de banda, ordenados por |Δ|) y bloque `provenance`
  ("datos usados"). Presencia GPS = asistencia.
- Funciones puras (`bands.py`, `labels.py`) para testear sin base:
  bandas simétricas, etiquetado MD con partido intermedio, empates.

### 8.4 API (`api/load_control.py`, registrada en `routers.py`)

| Método | Ruta | Permiso |
|---|---|---|
| GET | `/load-control/config` · PUT | ver / `change_load_plan` |
| GET | `/load-control/microcycles?bracket=&season=` | `view_load_control` |
| POST | `/load-control/microcycles` (`copy_from` opcional) | `change_load_plan` |
| GET / PUT | `/load-control/microcycles/{id}` (días + %) | ver / editar |
| POST | `/load-control/microcycles/{id}/open` (congela referencia) | `change_load_plan` |
| GET | `/load-control/evaluation?microcycle=&date=&sparring=` | `view_load_control` |

Permisos nuevos `core.view_load_control` y `core.change_load_plan` en
`Category.Meta.permissions`, migración que los asigna a los grupos Formativo
(Editor → ambos, Lectura → ver) y a Administrador.

### 8.5 Frontend

- Ruta `/control-carga?tab=planificacion|carga` (pestañas en la URL), con
  `RequirePermission`, entrada en `STATIC_NAV` (grupo Operativa) y
  `SEGMENT_LABELS`. Breadcrumb `Control de carga › Planificación › U20 · M41`.
- Equipo: se deriva del selector global (categoría → su `TeamSeason.bracket`)
  con chip visible "Mostrando U20 (Series 2006–2007)" (principio IA #5).
- Componentes nuevos: `PlanGrid` (días × métricas, celdas editadas
  resaltadas, partido bloqueado al 100%), `ReferenceTable`, `TargetCell`
  (óptimo / real + % + texto), `BandCounts`, `ExceptionList`,
  `DataProvenance`. Guardar → `toast.success`; abrir/congelar →
  `ConfirmDialog`.

### 8.6 Rebanadas y pruebas

1. ✅ **Ingest** (local, sin commit): campos nuevos en GPS + backfill. Ojo: la cuenta de servicio comparte cuota de lectura de Google con prod — no hacer lecturas masivas en horario de sync.
2. ✅ **Modelos + config + referencia** (local, sin commit): app `load_control`
   (`LoadControlConfig`, `Microcycle`, `MicrocycleDay`, migración 0001),
   `defaults.py` (todos los parámetros + `GroupResolver`), `labels.py` (MD±n con
   partido intermedio, hora local), `reference.py` (`compute_reference`,
   `day_targets`), `services.open_microcycle` (congela). `team_scope.season_rows`
   pública. 22 tests. Con datos reales al 26-oct: U20 DC sin jugadores > 75' →
   usa el equipo; U18 DFC sale de 1 jugador en 1 partido (Dinamarca 92′; 74′ el
   17-oct, a un minuto del corte). **Regla del club (2026-11-03): "siempre lo
   que use la U"** — no se inventan criterios. Un partido cuenta para el equipo
   cuya PESTAÑA lo registra (los de Serie 2008 que juegan con U20, o los de
   Primer Equipo que bajan, suman a U20, no a su categoría). Muestra mínima por
   grupo = parámetro `ref_min_players` (default 1 = sólo cae al equipo si no
   hay nadie); el valor real lo define el PF.
3. ✅ **Planificación** (local, sin commit): `load_control/planning.py`
   (sugerencia, crear, copiar % por etiqueta MD, editar, serializar),
   `load_control/matches.py`, API `api/load_control.py` (router en
   `/load-control`), permisos de modelo + migración 0002 a los grupos, pantalla
   `/control-carga` (PlanEditor + NewMicrocycleModal), menú y breadcrumb.
   Hallazgos con datos reales:
   - **Las fechas de los fixtures (`Event`) se corren 1–2 días** (Colo Colo
     jugado sáb 17 = Event lun 19). Fuente de días de partido = códigos
     `MD OFICIAL / MD AMISTOSO` del GPS; el fixture sólo cuenta si no hay
     partido en el GPS a ≤ 2 días (semanas futuras).
   - **Las etiquetas MD del club no siguen una regla fija** (vs. sus códigos
     2026: "partido siguiente" 84–88%, "más cercano" 72–78%). Un día con GPS
     toma el CÓDIGO del club (`md_label_source = club`); sólo los días sin GPS
     se calculan, con `md_label_rule` configurable (default "nearest") →
     **preguntar al PF qué regla usa al planificar**.
   - **Numeración distinta GPS vs. saltos**: Cobreloa 22-oct + U. Española
     25-oct = MICRO 41 en el GPS, pero "M40 CLOA / M40 UE" en la planilla de
     saltos U20. Resolver al importar saltos (mapear por fecha, no por número).
   - Pantalla no probada en navegador (sin sesión en Playwright); TypeScript y
     ESLint limpios, 303 tests backend.
4. ✅ **Evaluación + pestaña Carga GPS** (local, sin commit):
   `load_control/evaluation.py` (día o acumulado hasta hoy; real = sesiones +
   partido + compensación + sparring opcional; grupo = posición de la fila de
   ese día; bandas simétricas; alertas graves primero; resumen con conteos;
   "datos usados"), endpoint `GET /load-control/microcycles/{id}/evaluation`,
   `EvaluationView` (pestaña por defecto, filtros en la URL: `dia`,
   `sparring`, `partidos`). Suite completa backend: 1227 tests OK.
   Hallazgos con datos reales (U20 M41):
   - **Filas duplicadas en el GPS**: cuando el club recodifica una fila ya
     importada (vacío → NO MD, sesión → MD OFICIAL) el ingest guarda las dos
     copias (45 jugador-día en U20 2026, 16 = el partido del 22-oct). La
     evaluación las cuenta una vez (mismo minutos + distancia) y lo informa;
     ✅ **origen arreglado** (2026-11-03): cada sync borra las
     "copias obsoletas" — filas cuya identidad la planilla ya no produce y que
     son copia EXACTA (jugador, día, pestaña, minutos, distancia) de una que sí
     (`formativo_gps_ingest._copias_obsoletas`, `Reporte.duplicados_obsoletos`).
     En local: 60 borradas (U20 45 · U15 10 · U18 5). En prod se limpian solas
     en la primera sync tras el deploy. La deduplicación de la evaluación queda
     como red de seguridad.
   - El día de partido el objetivo es 100% para todos: el suplente aparece
     −70/−90% → es la "necesidad de compensar" acordada, no un error.
4b. ✅ **Partidos vinculados** (2026-11-03): cada día de partido apunta al
   partido cargado en SLAB (`MicrocycleDay.event`, `matches.match_links`):
   primero el que el ingest ya vinculó a las filas `gps_partido` de ese día,
   si no, el fixture a ≤ 2 días (sólo días oficiales: un amistoso nunca toma
   el oficial cercano). Rival desde el GPS. La pantalla muestra "vs RIVAL" con
   link a `/partidos/{id}`. **Partidos postergados**: el Event de COMET
   conserva la fecha PROGRAMADA (U20/U18 vs Cobreloa, fecha 12 = 12-oct) y sus
   fichas `ficha_partido` + el GPS la JUGADA (22-oct). La fecha efectiva de un
   partido es la de sus fichas COMET si existen (`matches.played_dates`); así
   desaparece el partido fantasma del 12 y el 22 queda vinculado. ✅ **Arreglado en el origen** (2026-11-03):
   - `comet_sync.played_kickoff_wins`: al ingerir un partido JUGADO, su fecha
     pasa a ser la del inicio real (fichas), si cambia el día local y la
     diferencia es ≥ 6 h. Comando `fix_postponed_match_dates` para lo ya
     guardado: **38 partidos juveniles** corregidos en local (postergados +
     el desfase sistemático de COMET, que fecha los fixtures juveniles el lunes
     de la semana de la fecha). Ninguno del Primer Equipo.
   - `core/localtime.py` (`local_date`, `CLUB_TIME_ZONE` = America/Santiago):
     el proyecto corre en UTC; el día de un INSTANTE (partido, ficha) se mide
     en hora local. Las filas GPS (sólo fecha, medianoche UTC) siguen en UTC.
   - Ingest GPS: una fila de partido sin vínculo lo vuelve a buscar en cada
     sync (`Reporte.eventos_vinculados`); en local 79 vinculadas (U20 22-oct
     incluidas), 221 siguen sin partido en SLAB.
   - Pendiente de verificar: algunas horas juveniles de COMET parecen hora
     local guardada como UTC (09:30 en Chile) → la HORA en /partidos podría
     estar 3 h corrida (el DÍA no).
   - Prod: deploy + `fix_postponed_match_dates --commit`; el re-vínculo GPS
     ocurre solo en la siguiente sync.
   Botones renombrados: "Publicar" (antes "Abrir y congelar") y "Guardar";
   estado "Publicado" (migración 0004).
5. **Demo con el PF** sobre un microciclo pasado real (M40 de U20, dos
   partidos: Cobreloa + U. Española) y ajustar antes de la Etapa 2.

## 9. Deploy — checklist (preparado 2026-11-03)

> Todo está **sin commit**. Orden pensado para prod (Railway, proyecto
> refreshing-ambition). One-offs en prod: `railway ssh --service backend
> "python manage.py …"` (ver memoria `project_railway_deploy`).

### 9.1 Antes del deploy

1. **Backup de prod** (regla de siempre: respaldar antes de tocar prod).
2. **Commit — ojo con los archivos compartidos.** `backend/api/routers.py`,
   `frontend/src/components/layout/Sidebar.tsx` y
   `frontend/src/components/layout/Breadcrumbs.tsx` tienen además cambios del
   trabajo "SLAB Admin / plataforma" (también sin commit). O se commitean
   juntos, o se separa con `git add -p`. Lo de este trabajo en esos archivos:
   - `routers.py`: sólo el bloque final que monta `/load-control`.
   - `Sidebar.tsx`: import `Gauge`, `PLANNING_NAV`, la sección
     "Planificación" y el `.filter` de secciones vacías.
   - `Breadcrumbs.tsx`: `"control-carga": "Control de carga"`.
3. Archivos de este trabajo:
   - **Nuevos:** `backend/load_control/` (app completa, migraciones 0001–0004),
     `backend/api/load_control.py`, `backend/api/test_load_control.py`,
     `backend/core/localtime.py`,
     `backend/exams/management/commands/fix_postponed_match_dates.py`,
     `frontend/src/app/(dashboard)/control-carga/`,
     `frontend/src/components/loadControl/`, `frontend/src/lib/loadControl.ts`,
     `PLAN_CONTROL_CARGA.md`.
   - **Modificados:** `backend/config/settings.py` (`load_control` en
     INSTALLED_APPS), `backend/core/management/commands/seed_role_groups.py`,
     `backend/dashboards/team_scope.py` (`season_rows`),
     `backend/exams/formativo_gps_ingest.py`,
     `backend/exams/management/commands/import_formativo_gps.py`,
     `backend/exams/services/comet_sync.py`, `backend/exams/tasks.py`,
     `backend/exams/test_comet_sync.py`, `backend/exams/test_formativo_gps_ingest.py`.
   - **No commitear:** `backend/celerybeat-schedule` (archivo de estado local de
     Celery beat) ni `.playwright-mcp/`.
4. Tests: suite backend completa (1244 OK en local) · `tsc --noEmit` y ESLint
   limpios en el frontend.

### 9.2 Deploy

5. **Migraciones** (no corren solas en el arranque):
   `railway ssh --service backend "python manage.py migrate"`
   → aplica `load_control.0001–0004`. La 0002 **asigna los permisos** de
   Control de carga a los grupos existentes (Administrador / Editor / Editor
   Formativo: ver + planificar; Solo Lectura / Lectura Formativo: ver). No hace
   falta re-correr `seed_role_groups` (si alguien lo corre, ya incluye
   `load_control` y deja lo mismo).
6. **Sin variables de entorno nuevas.** `CLUB_TIME_ZONE` es opcional
   (default `America/Santiago`).
7. Redeploy de **worker** y **beat** también (usan el código nuevo del ingest
   GPS y de COMET).

### 9.3 Después del deploy (en este orden)

8. **Fechas de partidos jugados (COMET)** — primero en seco, revisar, aplicar:
   ```
   railway ssh --service backend "python manage.py fix_postponed_match_dates"
   railway ssh --service backend "python manage.py fix_postponed_match_dates --commit"
   ```
   En local fueron 38 partidos juveniles (postergados + fixtures fechados en el
   lunes de la semana), 0 del Primer Equipo. Si en prod aparece alguno del
   Primer Equipo, **revisarlo antes del --commit**. Re-correr en seco debe dar 0.
   Desde el deploy, la sync de COMET corrige sola los partidos que se jueguen.
9. **Sync GPS formativo** — corre sola a los :25 de cada hora
   (`exams.tasks.sync_formativo_sheets`). Conviene esperar la del siguiente :25
   **después del paso 8**, porque es la que re-vincula las filas de partido
   con la fecha ya corregida. Esa primera corrida, una sola vez:
   - completa `posicion_hoja`, `tipo_microciclo`, `es_sparring`,
     `es_compensacion` en ~18.000 filas (bulk_update en lotes);
   - **borra las copias obsoletas** por recodificación (local: 60 · U20 45,
     U15 10, U18 5) → los dashboards de GPS dejan de contarlas doble;
   - **vincula** filas de partido que estaban sin partido (local: 79).
   Revisar el resultado de la tarea (`duplicados_obsoletos`,
   `eventos_vinculados`, `partido_actualizados`) en los logs del worker.
   ⚠️ **No** correr imports manuales en paralelo: la cuenta de servicio de
   Google comparte la cuota de lectura (60/min) con las syncs de prod.
10. **Verificar en prod:**
    - un usuario Editor Formativo ve **Planificación → Control de carga**; un
      Lectura Formativo la ve sin botones de edición;
    - `/partidos`: U20 vs Cobreloa (fecha 12) aparece el **22-oct**;
    - Control de carga → Nuevo microciclo semana 19-oct (U20): sugiere M41,
      partidos jue 22 (Cobreloa, con link) y dom 25 (U. Española), etiquetas
      MD-3 … MD como la planilla.

### 9.4 Pendientes que NO bloquean el deploy

- PF: muestra mínima por posición (`ref_min_players`), regla de etiquetas MD
  para semanas futuras (`md_label_rule`), numeración GPS vs. saltos, marcar
  `COMPENSACIÓN` en OBSERVACIÓN.
- Verificar si COMET guarda la hora juvenil como local-como-UTC (la HORA en
  /partidos podría estar 3 h corrida; el DÍA no).
- Pantalla `/control-carga` aún no revisada en navegador por nosotros.
