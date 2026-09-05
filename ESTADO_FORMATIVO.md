# Estado — integración de los datos de Formativo (U. de Chile)

Corte: **2026-09-02**. Todo aplicado en **local**; **nada** subido a prod.

- Plan y decisiones: `PLAN_FORMATIVO.md`
- Comandos, verificación y revert de cada fase: `RUNBOOK_FORMATIVO.md`

---

## 1. Resultado de esta etapa

El club entregó dos libros de Excel declarados como fuente de verdad del
formativo. Lo que había antes en SLAB para esas categorías era, en la práctica,
un plantel incompleto sin historia y sin un solo dato físico.

| | Antes | Ahora |
|---|---|---|
| Categorías | 12 | **16** |
| Jugadores | 314 | **479** |
| Con fecha de nacimiento | 313 | **472** |
| Con posición | 194 | **388** |
| Pertenencias con fecha | 310 (todas estimadas) | **469** (394 con fecha real) |
| Citaciones | 56 | **112** |
| Plantillas físicas | 0 | **5** |
| Resultados de evaluaciones físicas | **0** | **5061** |

Los 5061 resultados cubren **396 jugadores** entre el 2024-01-22 y el
2026-07-15: `carreras` 2119, `neuromuscular` 1413, `resistencia` 853, `fuerza`
666, `resistencia_1000m` 10.

**Fases cerradas:** 1 (CSV canónico), 2 (categorías y jugadores), 3
(pertenencias), 4 (plantillas), 6 (evaluaciones físicas).
**A medias:** 5 (bandas). **Sin empezar:** 7 (GPS), 8 (re-verificación).

### Lo que costó más que el código

El trabajo real no fue escribir importadores sino descubrir que **casi todas
las columnas derivadas del club son trampas**. Cinco casos, cada uno detectado
antes de escribir datos y cada uno silencioso:

1. **`CATEGORÍA` no es un dato, es una fórmula.**
   `IFS(YEARFRAC(nacimiento, TODAY()) > umbral, …)`. Fecha vacía → 126 años →
   todo cae en `U21`. Nacidos en octubre–diciembre de la cohorte más chica se
   caen del `IFS` y dan `#N/A`. Y con `TODAY()` la etiqueta cambia sola con el
   reloj. Los "7 homónimos de Sub 20" que yo había afirmado eran filas
   duplicadas de chicos de U13–U15.
2. **`min([a],[b],[c])` devolvía `None` con dos intentos**, que es el caso
   mayoritario (2978 de 4341 filas). Se habrían cargado 15.000 filas con todos
   los gráficos y todas las alertas vacíos, sin un solo error.
3. **La columna que nombra el test en `CARRERAS` está titulada
   `NEUROMUSCULAR`** — el club copió la hoja. Buscarla por el nombre de la hoja
   leyó 0 de 4341 filas y la corrida se reportó limpia.
4. **`PRESS DE BANCO` tiene un `FECHA` fantasma al frente**, así que cada valor
   está una columna a la izquierda de su encabezado: `PESO CORPORAL` se leía de
   la posición.
5. **Las cargas no intentadas vienen en `0`**, no vacías, y se llevaban 678 de
   682 sesiones de `FUERZA` por el piso de 0,1 m/s.

De ahí sale la regla que quedó aplicada en todo: **se importa el hecho y se
calcula el resto.** La cohorte, no la etiqueta Sub N. Los intentos, no el
`BEST`. El palier, no los metros ni el VO₂. Con dos excepciones explícitas —
`vam` es un lookup de 91 filas que el motor de fórmulas no puede hacer, y el
`vo2_max` de los 1000 m no es función sólo del tiempo (240 s da 48,3 y 251 s da
51,1).

**El techo de `Bracket.for_age` hubo que frenarlo tres veces.** Devuelve Sub 11
para un chico de 8 años, correcto para su pregunta y equivocado cuando la
pregunta es "qué compite esta cohorte". Sin guard, las Series 2016–2018 pasaban
un corte de "Sub 11 y más" y quedaban con GPS que nunca corrieron.

**Y `SUB-20` se queda como lo llama el club.** La primera corrida partió ese
plantel en Serie 2004–2007 y quedaron cuatro categorías de 0 a 5 jugadores
compitiendo con la real por las mismas 43 personas: un modelo más limpio que
nadie en el club podía usar.

**570 tests en verde** entre `core`, `exams` y `goals`, 79 nuevos en esta etapa.

---

## 2. Pendiente nuestro — bloqueante

### 2.1 ⚠️ Rotar los secretos de prod

En una sesión anterior corrí `railway variables` sin filtrar y **cuatro
secretos de producción quedaron en el log de la conversación**:
`ANTHROPIC_API_KEY`, `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`,
`DJANGO_SECRET_KEY` y la password de Redis. Recomendé rotarlos y **no hay
confirmación de que se haya hecho**.

Es lo primero de esta lista por una razón: no depende del club, no depende de
ninguna fase, y el riesgo corre desde entonces.

Para el futuro: `railway variables` sólo con las claves, nunca los valores.

### 2.2 ✅ Fase 5 — hecha (2026-09-02)

`seed_formativo_bands` parsea las dos hojas `FORMATO CONDICIONAL` y siembra
**66 reglas** con `config["ranges"]` propios, una por (categoría, campo) sobre
los 10 tests que el club escaló. Y `/configuraciones/alertas` ahora tiene un
**editor de umbrales**, así que el cuerpo médico puede revisarlos y ajustarlos
sin tocar la base.

### 2.3 ✅ Fase 7 — GPS importado (2026-09-02)

**15.352 resultados**: 3501 `gps_partido` (1649 vinculados a su evento) y
11.851 `gps_sesion`, 305 jugadores, 2025-01-08 → 2026-09-01. Con eso el cruce
que el club pidió ya funciona:

| Categoría | DT medio en partido | HSR medio |
|---|---|---|
| Primer Equipo | 9559 m | 920 m |
| SUB-20 | 8065 m | 664 m |
| Serie 2010 | 7918 m | 565 m |
| Serie 2013 | 7328 m | 376 m |
| Serie 2015 | 4844 m | 124 m |

⚠️ Primer Equipo viene de Catapult (HSR > 19,8 km/h) y el formativo de la
planilla (> 20). El gradiente es fisiológicamente coherente, así que la
diferencia no distorsiona la lectura gruesa, pero la clave de procedencia
permite auditarlo cuando importe.

### 2.4 ✅ Wellness del formativo — plantillas y superficies listas (2026-09-04)

El club **no sigue la regla de Primer Equipo**, así que no se reusa
`checkin_fisico`. Se hizo lo que faltaba del lado nuestro:

**Las plantillas** (`seed_wellness_formativo`, 12 categorías):
`checkin_formativo` (13 campos) y `checkout_formativo` (16 campos). `SUMA` y
`UA` se **calculan**, no se importan — sus encabezados son inconsistentes entre
los ocho documentos (`SUMA` en cuatro, un `0` pelado en uno, `UA` en seis y
`AU` en uno) y una columna cuyo nombre es un typo es como una métrica se vacía
en silencio.

**La plantilla declara su escala.** `config_schema["wellness"]` lleva `role`,
`items`, `inverted` y `dimensions`, y `api/wellness.py` los lee en vez de
tenerlos hardcodeados. Vive en el schema y no en una columna del modelo porque
así **se versiona con el formulario**: cuando el club lo cambie, la versión
nueva trae sus propios ítems en vez de que los viejos sigan aplicando calladamente.
Una plantilla sin bloque `wellness` cae a las constantes anteriores, que es
exactamente lo que `checkin_fisico` declaraba de forma implícita.

**Las superficies dejaron de mirar el slug.** El Daily, el Centro de mando,
`readiness` y el roster resuelven la plantilla por categoría. Sin esto los
65.000 check-ins del formativo entraban a una pantalla que consultaba
`checkin_fisico`, no encontraba nada y reportaba "0/68 respondieron" — igual
que un plantel que no contestó.

⚠️ Tres de los cinco ítems del formativo están **invertidos** (fatiga, estrés,
daño muscular) contra los cinco de Primer Equipo que apuntan todos igual.
Promediarlos crudos le da 84 a un jugador destruido, y el número sigue
pareciendo un puntaje de wellness. Por eso existe `score_for(category, data)`:
resuelve ítems, máximos e invertidos juntos, y **hay que usarlo en vez de
`score()`**.

**El check-out en el frontend** (2026-09-04): el payload trae `wellness_roles`
por categoría y el toggle Check-IN/Check-OUT aparece sólo donde hay las dos
formas. Está en el KPI de wellness y en la tarjeta de adherencia del Centro de
mando, y en el KPI del Daily. El estado va en la URL (`?wellness=checkout`),
como el resto de las pestañas de la app. Primer Equipo no ve toggle ni fila
"Check-OUT" en calidad de datos: un "Sin plantilla" ahí se leería como una
falla de configuración y no como un formulario que ese plantel nunca llenó.

**El importador y el cron — hechos (2026-09-05).** 117.395 filas leídas,
**109.914 importadas**: 60.341 check-in y 49.573 check-out, del 15/01/2024 al
04/09/2026. Tres entradas de Celery Beat mantienen los ocho documentos al día
(ventana de 7 días en la jornada, barrido completo los domingos); una corrida
mide 39,5 s.

Quedó afuera un 6,4%: **6741 filas de 69 nombres sin jugador en SLAB** —
casi todos ex-jugadores cuya última respuesta es de 2024 — y **738 filas de dos
homónimos** (`DAVID GUZMAN`, `FRANCO CÁCERES`) que la cohorte del documento no
desempata. Los únicos nombres recientes sin resolver son **JOHN CORTES**,
**NICOLAS MARCANO** y **CHRISTIAN ROZAS**, que hay que ver con el club.

⚠️ **Dos correcciones que el relevamiento obligó.** La escala **no está
invertida**: en este formulario 5 es lo mejor para los cinco ítems, fatiga y
daño muscular incluidos, verificado contra la columna `SUMA` del club (25.146
filas coinciden al 100% con la suma cruda, 0 con la invertida). Y el check-out
**mide carga, no bienestar**: `rpe` viene en el 100% de las filas y
`dano_muscular` en el 8%, y cuatro de los ocho documentos no lo preguntan — así
que su KPI muestra carga interna (UA) con tono neutral en vez de un puntaje
0–100 que habría dicho "Sin datos" para siempre en media plantilla.

**Bandas, alertas y layouts — hechos (2026-09-05).** 18 reglas `band` (dos por
campo vigilado, sin categoría porque un 3 de sueño significa lo mismo en las
doce), las bandas 1–5 en el campo, y los layouts regenerados: 8 widgets de
jugador + 6 de equipo por categoría. La ficha de un jugador de Serie 2011
muestra 8 secciones y 30 widgets, todos con datos. **113 alertas activas** (20
críticas) tras evaluar los últimos 30 días.

⚠️ **`hidratacion` no es una escala 1–5.** Va de 1 a 9 y el 78% de las 46.512
respuestas son 2 o 3: son litros de agua, donde 2 es lo normal. Sembrada con la
banda de escala marcaba el 55% de las respuestas como críticas — 284 alertas
falsas de 397. Quedó sin banda y sin regla: cuántos litros son pocos lo decide
el cuerpo médico.

⚠️ **`FORMATIVO_GPS_SHEET_ID` y `FORMATIVO_EVAL_SHEET_ID` nunca llegaban al
contenedor**: estaban en `settings.py` pero no en el bloque `environment` de
`docker-compose.yml`, así que el sync horario de GPS y evaluaciones fue un
no-op silencioso desde que se escribió. Corregido en los tres servicios.

### 2.5 Desplegar

**22 commits sin subir.** Es toda esta etapa más las anteriores. Local está por
delante de prod y la brecha crece con cada fase.

⚠️ Antes de correr la fase 2 en prod: **no tiene revert automático.** Es
aditiva pero no marca lo que creó. Tomar un dump primero.

---

## 3. Pendiente nuestro — no bloqueante

### 3.1 ✅ Bandas del lado de la visualización — hecho (2026-09-02)

`dashboards/category_bands.py` resuelve la banda por categoría y la inyecta
donde se serializa, vía el mismo patrón de `ContextVar` que ya usan el flag de
secundarios en `team_aggregation` y el ancho de columna en los renderers de
PDF. Sin eso habría que pasar un parámetro por 14 resolvedores para un lookup.

Al hacerlo apareció que **sólo cinco tipos de gráfico emiten bandas**:
`comparison_table`, `line_with_selector` y `grouped_bar` del lado del jugador,
`team_roster_matrix` y `team_distribution` del lado del equipo. `multi_line`
calcula el meta y no lo serializa, así que ahí la banda nunca llegaba al
frontend. Importa para los layouts: si se quiere ver la banda sobre una línea,
el widget es `line_with_selector`, no `multi_line`.

### 3.2 `BulkIngestForm` no muestra las filas rechazadas

El backend ya devuelve los rechazos con su motivo; la UI muestra sólo
`matched_players` y `unmatched.length`. Quien sube un archivo ve "0
emparejados" sin saber por qué — y después de esta etapa sabemos exactamente
cuánto se puede esconder detrás de eso.

### 3.3 Auditoría de filtros por categoría

46 sitios en `api/` filtran `category=` en crudo contra 94 usos del helper
canónico (`players_in_category` / `scope_players`). Cada sitio crudo es un
lugar donde un jugador citado no aparece, o aparece donde no debería. La regla
es: **acceso = origen ∪ citaciones activas; conteo = sólo origen.**

### 3.4 ✅ `Category.departments` — era bloqueante, no cosmético

Lo había clasificado como "no bloquea exámenes, sólo vacía la lista del
reporte diario". **Estaba equivocado.** La ficha del jugador arma sus pestañas
de departamento con `player.category.departments`
(`perfil/[id]/page.tsx:130`), así que con la M2M vacía los 20 layouts
generados eran inalcanzables desde la ficha de cualquier jugador: existían y
no había forma de llegar a ellos.

Ahora lo vincula `generate_formativo_layouts`, que es donde ya se sabe que hay
algo que mostrar. Sólo agrega, nunca saca, para no pisar un departamento que
el club vinculó a mano. Un departamento sin layout **no** se vincula: la
pestaña renderizaría un panel vacío, que se lee como "faltan datos".

### 3.5 `seed_fatiga_central` tiene el bug que la fase 4 corrigió

Filtra las categorías por `Category.departments`, y en este club sólo
`Primer Equipo` los tiene vinculados: su plantilla probablemente aplica sólo a
Primer Equipo. Es de otro departamento, así que no se tocó.

### 3.6 `quick_list` declarado y nunca implementado

Está en `exams/models.py`, en `lib/types.ts` y en el diccionario de etiquetas
de la página de registro, pero no hay componente. Si una plantilla lo declara
como modo, la pantalla no ofrece nada. Decidir: implementarlo o sacarlo.

### 3.7 Dos defectos con nombre y apellido

- **`NAME_FIX_BY_DOB` es código muerto** en `build_formativo_master.py`.
  `CLUB_CONFIRMED` está indexado por nombre y corre antes, así que le cambia la
  fecha y la clave `(nombre, fecha)` nunca coincide. Los dos David Guzmán
  quedaron bien separados igual —`BASCUR` 2011-02-10 Serie 2011, `VIVANCO`
  2008-06-09 Serie 2008, posiciones incluidas— pero por las hojas de sesión,
  que traen el apellido correcto, no por el mecanismo que escribí. Si el club
  entrega los datos sin ese respaldo, la corrección no actúa.
- **`implied_cohort` no sirve en los brackets altos.** La inversión
  etiqueta→cohorte sólo vale cuando el jugador juega su propio peldaño; en Sub
  18 y Sub 20 no hay a dónde subir, así que quien se queda ahí varias
  temporadas invierte a una cohorte móvil (248 de 501 lo muestran). Se usa sólo
  para los 7 sin fecha de nacimiento y va marcada como estimación.

### 3.8 Mantenimiento por temporada

`seed_formativo_templates` **hay que volver a correrlo cada temporada**. "Quién
hace el test" es un peldaño ("Sub 13 y más") pero `applicable_categories`
guarda categorías, así que la respuesta cambia todos los años: una Serie 2015
que hoy es Sub 11 será Sub 13 en 2028 y ahí le toca Resistencia.

---

## 4. Pendiente del club

| # | Qué | Cuánto | Detalle |
|---|---|---|---|
| 1 | Fechas de nacimiento | 9 | 3 de plantel (Guerrero U20, Rivera U15, Valdés U16) y 4 sin plantel ni fecha (Bakhit, Ahumada, Camus, Muñoz), más 2 sin resolver. En `formativo_pendientes.csv` |
| 2 | Filas sin fecha de sesión | 200 | 119 en `PRESS DE BANCO` (la hoja **no tiene** columna de fecha), 62 en `1000 METROS`, 15 en `NEUROMUSCULAR`, 4 en `RESISTENCIA` |
| 3 | Nombres sin jugador | 16 | typos (`DAMINA SOLIS` por Damián Solís) y filas con sólo apellido (`OLIVEROS`, `CORNEJO`) |
| 4 | Celdas con valores imposibles | 7 | `v_60kg=45992` y `=45658` (números de fecha en una columna de velocidad), un T30 de 2,68 s (30 m a 40 km/h), un tiro a 4 km/h, un `cod_izq=34,03` |
| 5 | Fechas arrastradas | 2 | `2012-01-04` en 4 jugadores y `2006-05-26` en 3. En este último la base tiene las tres fechas correctas y el archivo la arrastrada |
| 6 | Desacuerdos de categoría de un año | 10 | Serie↔Serie, donde cualquiera de los dos lados puede tener razón |
| 7 | Umbral de HSR | — | La planilla usa **> 20 km/h** y Catapult **> 19,8**. Se tratan como equivalentes por decisión del cliente; es un **supuesto**, y el sesgo es sistemático en una sola dirección: subestima al juvenil, justo en la comparación que ellos pidieron |
| 8 | Nomenclatura del femenino | — | `PEF - Femenino`, `SUB-16 F`, `SUB-19 F` quedaron fuera de esta etapa: los libros del formativo no las cubren |

Los ítems 2 a 5 no bloquean nada: lo importable ya está importado y esas filas
quedaron listadas por los propios importadores.

---

## 5. ✅ Layouts de equipo y de jugador — hechos (2026-09-02)

Pedido: analizar los exámenes y crear **team layouts** y **player layouts** para
todas las categorías.

`generate_formativo_layouts` los arma desde el dato:

| | |
|---|---|
| Layouts de jugador | **20** · 245 widgets |
| Layouts de equipo | **20** · 171 widgets |

El reparto sigue lo que cada categoría mide: SUB-20 con 7 secciones en físico,
Serie 2018 con 1 (sólo carreras), Series 2013–2008 con 6, y táctico en las 8
que tienen partidos. Psicosocial y kinesiológico no reciben nada porque tienen
cero resultados.

⚠️ **1204 resultados quedaron fuera de todo dashboard** y el comando los
reporta aparte: viven en plantillas que **no aplican** a esas categorías —
1165 de `pentacompartimental` (aplica sólo a Primer Equipo, y los importó
`import_pentacompartimental` sin ampliar la aplicabilidad) y 39 de médico. O
se amplía `applicable_categories`, o no se pueden graficar.

### Qué datos hay realmente, por categoría y departamento

Esto es lo que determina qué layout corresponde a cada una — no se replica el
de Primer Equipo, porque los exámenes son distintos:

| Categoría | físico | táctico | nutricional | médico |
|---|---|---|---|---|
| `SUB-20` | 1013 | 841 | 311 | 66 |
| Serie 2011 | 626 | 880 | 168 | — |
| Serie 2012 | 573 | 741 | 121 | — |
| Serie 2010 | 679 | 616 | 148 | — |
| Serie 2013 | 480 | 651 | 68 | — |
| Serie 2014 | 404 | 730 | 79 | — |
| Serie 2009 | 553 | 488 | 173 | — |
| Serie 2008 | 346 | 135 | 97 | 4 |
| Serie 2015 | 146 | — | — | — |
| Serie 2016 / 2017 / 2018 | 33 / 33 / 16 | — | — | — |

Dos consecuencias de diseño que salen de esa tabla:

- **Un layout por (categoría, departamento) sólo donde hay datos.** Generar los
  cuatro departamentos para Serie 2018 daría tres pantallas vacías. Son ~30
  layouts de jugador y ~30 de equipo, no 12 × 6.
- **Las series chicas llevan un layout más corto.** Series 2016–2018 sólo
  corren `carreras` y `neuromuscular`; Resistencia y Fuerza empiezan en Sub 13.
  El layout tiene que salir de los campos que **tienen valores**, no del
  esquema de la plantilla.

### Orden recomendado

Generar los layouts **después** de las fases 7 y 5, no antes:

1. **Fase 7 (GPS)** primero. Va a agregar el volumen más grande al
   departamento físico, y un layout generado hoy nace sin widgets de GPS —
   habría que regenerarlo igual.
2. **Fase 5 (bandas)** antes o en paralelo. Sin los umbrales del club los
   gráficos dibujan la banda del default compartido, así que a un Sub 11 se le
   pinta la banda de un Sub 20 (§3.1). Un dashboard con la banda equivocada es
   peor que ninguno: se ve correcto.
3. **Layouts**, generados por comando y **re-corrible**, para que la llegada de
   datos nuevos no obligue a rehacerlos a mano.

### Lo que hay que decidir antes de escribir el comando

- **¿Un layout por serie o uno por peldaño?** Un layout por serie son ~30 que
  hay que editar de a uno. Uno por peldaño (Sub 11, Sub 13, …) se comparte,
  pero `DepartmentLayout` y `TeamReportLayout` tienen FK a `Category`, no a
  `Bracket`, así que hoy no se puede sin cambiar el modelo. Sospecho que lo
  correcto es **plantilla por peldaño, instanciada por categoría** por el mismo
  comando, pero es una decisión de producto.
- **¿Qué se pone en cada uno?** Propongo derivarlo del dato: un widget de línea
  por campo con `chart_type` y valores, agrupado por la sección que ya declara
  el `group` del campo. Eso hace el layout una consecuencia de las plantillas y
  no una lista paralela que se desincroniza.
- **El `scope` de los team layouts.** Los de Primer Equipo usan `period` salvo
  uno global con `match`. Para el formativo, `period` es lo que corresponde
  mientras no haya GPS de partido cargado.

---

## 6. Lo que no se tocó a propósito

Vale dejarlo escrito para que no parezca olvido:

- **No se partió el GPS entre Primer Equipo y proyección.** Las columnas del
  formativo son un subconjunto estricto de `gps_sesion` (los 13 métricos ya
  tienen campo y `gps_sesion` tiene 16 más). Partirlo rompería la comparación
  entre plantel y cantera, que es lo que el club pidió, y el eje que de verdad
  importa es el **proveedor**, no el equipo.
- **No se movió a nadie de categoría** (17 desacuerdos) ni se pisó ninguna
  fecha (13 conflictos). Los flags existen y están apagados.
- **Las 56 citaciones nuevas van inactivas.** `active=True` ensancha el acceso
  a datos de menores; concederlo desde una planilla es un cambio de permisos,
  no una importación.
- **Los 80 jugadores a prueba no se importaron** como plantel. La hoja del club
  no les registra fecha de nacimiento, y no son del plantel.
